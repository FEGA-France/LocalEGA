"""
Async file I/O with automatic io_uring / executor fallback.

Backend selection (at import time)
-----------------------------------
 1. Try to import liburing and probe the kernel with a real queue_init call.
    If both succeed  →  _Ring     (io_uring backend, Linux ≥ 5.1)
 2. Otherwise        →  _RingFallback  (ThreadPoolExecutor backend,
                         works on macOS, old kernels, Docker-on-Mac, …)

The two backends share the same _RingBase interface so AsyncTransfer is
completely unaware of which one is active.  A module-level constant
BACKEND ('io_uring' | 'executor') exposes the selection to callers.

io_uring architecture
----------------------
                 ┌─────────────────────────────────┐
                 │           asyncio loop          │
                 │  (epoll / SelectorEventLoop)    │
                 └──────────────┬──────────────────┘
                                │  loop.add_reader(eventfd_fd, ...)
                                ▼
                         ┌─────────────┐
                         │   eventfd   │  ← io_uring signals here on every CQE
                         └──────┬──────┘
                                │
                 ┌──────────────▼──────────────────┐
                 │           io_uring              │
                 │  SQE queue  ──►  kernel         │
                 │  CQE queue  ◄──  kernel         │
                 └─────────────────────────────────┘

executor fallback architecture
-------------------------------
                 ┌─────────────────────────────────┐
                 │           asyncio loop          │
                 └──────────────┬──────────────────┘
                                │  loop.run_in_executor(pool, ...)
                                ▼
                 ┌─────────────────────────────────┐
                 │      ThreadPoolExecutor         │
                 │  thread: fh.readinto(mv)        │
                 │  thread: fh.write(data)         │
                 └─────────────────────────────────┘

 readinto() uses fh.readinto(memoryview(buffer)[:n]) — the OS writes
 directly into the pre-allocated bytearray; the only allocation is the
 memoryview header (a few words on the stack).

Usage (identical regardless of backend)
-----------------------------------------

   rctx = PosixStream()
   wctx = PosixStream()

   async with rctx.open("src.bin", "r") as reader,
              rctx.open("dst.bin", "w") as writer:
       buffer = bytearray(min(reader.CHUNK_SIZE, writer.CHUNK_SIZE))
       while True:
           n = await reader.readinto(buffer)
           if n == 0:
               break
           process(buffer[:n])           # transform in-place
           await writer.write(buffer[:n])

Why not O_DIRECT?
-----------------
O_DIRECT is unsupported (EINVAL) on NFS and CephFS, unavailable inside
Docker on macOS, and buys nothing on network storage where the bottleneck
is always the network, not the page cache.

Why not a thread pool for each call?
-------------------------------------
os.pread / os.pwrite are blocking syscalls.  Dispatching them one-at-a-time
to run_in_executor means one OS thread stalls for the full round-trip of
every single call.  For local SSDs that round-trip is microseconds; for
NFS or Ceph it can be tens or hundreds of milliseconds, quickly exhausting
the default ThreadPoolExecutor(max_workers=…) pool under any concurrency.

The approach here: open the files in *non-blocking* mode and let the event
loop do the multiplexing via add_reader / add_writer, with a plain bytearray
for buffering.  This is the same model asyncio uses internally for sockets
and pipes.

Caveats
-------
* O_NONBLOCK on *regular* files is ignored by the kernel on Linux – reads and
  writes on regular files always complete immediately from the VFS/page-cache
  perspective, so the kernel never actually blocks the fd.  The event loop's
  add_reader / add_writer still work because the fd is always "readable" and
  "writable"; the actual I/O happens in the callback without stalling the loop
  for more than one syscall quantum.

* For truly async disk I/O on local files where kernel read latency matters,
  io_uring is the right tool (be it with network files over NFS / CephFS / S3FS, or not).

* Writes are flushed with os.fsync() inside __aexit__ to ensure data is
  durable before the fd is closed.  Pass fsync=False to skip this (e.g. for
  intermediate temporary files).
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path

from . import FileStream

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# io_uring probe — attempt import + a real queue_init to catch kernel rejects
# ---------------------------------------------------------------------------
# Return (liburing_module, iovec_class) if io_uring is fully usable,
# or (None, None) if the import fails or the kernel rejects queue_init.
#
# We do a real io_uring_queue_init() call because some environments (e.g.
# Docker on macOS with a Linux VM) have a new-enough kernel version string
# but disable io_uring via seccomp / sysctl.
try:

    if os.getenv('IO_URING', None) == 'no':
        raise ValueError('Disabled by environment variable IO_URING')
   
    import liburing as _lu

    ring = _lu.io_uring()
    _lu.trap_error(_lu.io_uring_queue_init(8, ring, 0))
    _lu.io_uring_queue_exit(ring)
    _BACKEND = 'io_uring'
    _liburing = _lu

except Exception as exc:

    LOG.debug("io_uring unavailable (%s), using executor fallback", exc)
    _liburing = None
    _BACKEND = 'executor'

# ---------------------------------------------------------------------------
# Abstract base — the interface AsyncTransfer talks to
# ---------------------------------------------------------------------------

class _RingBase(ABC):

    ring: None
    ready: bool = False

    @abstractmethod
    def setup(self) -> None: ...

    @abstractmethod
    def teardown(self) -> None: ...

    @abstractmethod
    def submit_read(
            self, fd: int, buffer: bytearray, size: int, offset: int,
            fut: asyncio.Future,
    ) -> None: ...

    @abstractmethod
    def submit_write(
            self, f, buffer: memoryview | bytearray | bytes, # size: int, # offset: int,
            fut: asyncio.Future,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Backend A — io_uring  (Linux ≥ 5.1, liburing installed)
# ---------------------------------------------------------------------------

class _Ring(_RingBase):
    """
    io_uring backend.  Each submit_* call pushes one SQE; completions are
    delivered to asyncio via an eventfd that loop.add_reader watches.
    """

    QUEUE_DEPTH = 8

    def __init__(self, loop):
        self.ring = _lu.io_uring()
        self.efd  = -1
        self.pending: dict[int, asyncio.Future] = {}
        self.token_counter = 0
        assert loop, "Invalid async loop"
        self.loop = loop
        self.ready = False

    def setup(self):
        if self.ready:
            return
        LOG.debug('Creating io_uring queue')
        _liburing.trap_error(_liburing.io_uring_queue_init(self.QUEUE_DEPTH, self.ring, 0))
      
        self.efd = os.eventfd(0, os.EFD_NONBLOCK)
        _liburing.trap_error(_liburing.io_uring_register_eventfd(self.ring, self.efd))

        self.loop.add_reader(self.efd, self._on_cqe_ready)
        self.ready = True

    def teardown(self) -> None:
        if not self.ready:
            return
        LOG.debug('Tearing down io_uring queue')
        try:
            self.loop.remove_reader(self.efd)
        except Exception:
            pass
        efd, self.efd = self.efd, -1
        if efd >= 0:
            os.close(efd)
        _liburing.io_uring_queue_exit(self.ring) # will io_uring_unregister_eventfd
        self.ready = False
        self.token_counter = 0
        # Cancel the pending futures
        for fut in self.pending.values():
            fut.cancel() 
        self.pending = dict()

    # ------------------------------------------------------------------

    def _next_token(self) -> int:
        self.token_counter = (self.token_counter + 1) & 0xFFFF_FFFF_FFFF_FFFF
        return self.token_counter

    def submit_read(
            self, fd: int, buffer: bytearray, size: int, offset: int,
            fut: asyncio.Future,
    ) -> None:
        if not self.ready:
            raise RuntimeError('First set up the ring')
        iov   = _liburing.iovec(buffer)          # points into buffer — no copy
        token = self._next_token()
        self.pending[token] = fut
        sqe = _liburing.io_uring_get_sqe(self.ring)
        _liburing.io_uring_prep_read(sqe, fd, iov.iov_base, size, offset)
        _liburing.io_uring_sqe_set_data64(sqe, token)
        _liburing.trap_error(_liburing.io_uring_submit(self.ring))

    def submit_write(
            self, fd: int, data: bytes | bytearray | memoryview, size: int,
            offset: int, fut: asyncio.Future,
    ) -> None:
        if not self.ready:
            raise RuntimeError('First set up the ring')
        buf = data if isinstance(data, (bytearray, memoryview)) else bytearray(data)
        iov   = _liburing.iovec(buf)
        token = self._next_token()
        self.pending[token] = fut
        sqe = _liburing.io_uring_get_sqe(self.ring)
        _liburing.io_uring_prep_write(sqe, fd, iov.iov_base, size, offset)
        _liburing.io_uring_sqe_set_data64(sqe, token)
        _liburing.trap_error(_liburing.io_uring_submit(self.ring))
        

    # ------------------------------------------------------------------
    def _on_cqe_ready(self) -> None:
        """Called by asyncio when the eventfd becomes readable."""
        try:
            os.read(self.efd, 8)       # drain counter to re-arm
        except BlockingIOError:
            pass
        cqe = _liburing.io_uring_cqe()
        while True:
            ret = _liburing.io_uring_peek_cqe(self.ring, cqe)
            if ret != 0:                # -EAGAIN → queue empty
                break
            token = cqe.user_data
            res   = cqe.res
            _liburing.io_uring_cqe_seen(self.ring, cqe)
            fut = self.pending.pop(token, None)
            if fut is None or fut.done():
                continue
            if res < 0:
                fut.set_exception(OSError(-res, os.strerror(-res)))
            else:
                fut.set_result(res)


# ---------------------------------------------------------------------------
# Backend B — ThreadPoolExecutor fallback  (macOS, old kernels, …)
# ---------------------------------------------------------------------------

class _RingFallback(_RingBase):
    """
    Executor-based fallback.
    
    readinto uses os.readinto(fd, memoryview(buffer)[:size]) so the OS
    writes directly into the pre-allocated bytearray — same zero-copy
    property as the io_uring path, just offloaded to a thread instead of
    submitted as an SQE.
    """

    def __init__(self, loop, max_workers=2, prefix="async_posix"):
        self.pool = None
        assert loop, "Invalid async loop"
        self.loop = loop
        self.max_workers = max_workers
        self.prefix = prefix
        self.ready = False

    def setup(self):
        if self.ready:
            return
        LOG.debug('Creating ThreadPool: worker %s | prefix: %s', self.max_workers, self.prefix)
        from concurrent.futures import ThreadPoolExecutor
        self.pool = ThreadPoolExecutor(max_workers=self.max_workers,
                                       thread_name_prefix=self.prefix)
        self.ready = True

    def teardown(self):
        if not self.ready:
            return
        LOG.debug('Tearing down ThreadPool')
        if self.pool:
            self.pool.shutdown(wait=False)
            self.pool = None
        self.ready = False

    # ------------------------------------------------------------------

    def submit_read(
            self,
            fd: int,
            buffer: bytearray | memoryview | bytes,
            offset: int,
            fut: asyncio.Future,
    ) -> None:
        if not self.pool:
            raise RuntimeError('First set up the ring')
        self._chain(self.loop.run_in_executor(self.pool, os.preadv, fd, [buffer], offset), fut)

    def submit_write(
            self,
            fd: int,
            data: bytes | bytearray | memoryview,
            offset: int,
            fut: asyncio.Future,
    ) -> None:
        if not self.pool:
            raise RuntimeError('First set up the ring')
        self._chain(self.loop.run_in_executor(self.pool, os.pwritev, fd, [data], offset), fut)

    # ------------------------------------------------------------------

    @staticmethod
    def _chain(
            executor_future: asyncio.Future,
            caller_future:   asyncio.Future,
    ) -> None:
        """Forward result/exception from the executor Future to the caller Future."""
        def _on_done(f: asyncio.Future) -> None:
            if caller_future.done():
                return
            exc = f.exception()
            if exc is not None:
                caller_future.set_exception(exc)
            else:
                caller_future.set_result(f.result())

        executor_future.add_done_callback(_on_done)

# ---------------------------------------------------------------------------
# Monkeypatch: point _Ring at the right backend at import time
# ---------------------------------------------------------------------------

if _liburing is None:
   _Ring = _RingFallback          # type: ignore[misc]

LOG.debug('Posix files, using backend: %s', _BACKEND)

# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

def os_flags(mode: str) -> int:
    m = set(mode)
    flags: int = 0
    rwa = False
    readable = False
    writable = False
    if "x" in m:
        if rwa:
            raise ValueError('Bad flags')
        flags |= os.O_EXCL | os.O_CREAT
        rwa = True
        writable = True
    if "r" in m:
        if rwa:
            raise ValueError('Bad flags')
        rwa = True
        readable = True
    if "w" in m:
        if rwa:
            raise ValueError('Bad flags')
        flags |= os.O_CREAT | os.O_TRUNC
        rwa = True
        writable = True
    if "a" in m:
        if rwa:
            raise ValueError('Bad flags')
        flags |= os.O_CREAT | os.O_APPEND
        rwa = True
        writable = True
    if "+" in m:
        readable = True
        writable = True
    if "e" in m:
        flags |= os.O_EXCL
    if "n" in m:
        flags |= os.O_NONBLOCK

    if not rwa:
        raise ValueError('Bad flags: should have at least "r", "w" or "a"')

    if readable and writable:
        flags |= os.O_RDWR # or not supported ?
    elif readable:
        flags |= os.O_RDONLY
    elif writable:
        flags |= os.O_WRONLY

    return flags

class PosixStream(FileStream):
    """Local file, read/write through the ring (io_uring or executor)."""

    # CHUNK_SIZE: int = 1 << 23  # 8MB, default

    def __init__(self,
                 rootdir = None,
                 ring = None,
                 loop: asyncio.AbstractEventLoop = None) -> None:

        self.loop  = loop or asyncio.get_running_loop()
        self.ring: _RingBase = ring or _Ring(self.loop)  # io_uring or fallback, decided above

        if rootdir:
            if not os.path.isdir(rootdir):
                raise ValueError(f'Invalid rootdir: {rootdir}')
            rootdir = Path(rootdir)

        self.rootdir = rootdir

        # After open
        self.fd = -1
        self.offset = 0
        self.size = 0
        # LOG.debug('Created PosixFile %s', id(self))

    def __str__(self):
        return f'<PosixStream | rootdir:{self.rootdir}>' 

    def __enter__(self) -> "PosixStream":
        self.ring.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        LOG.debug('__exit__: %s, %s, %s', exc_type, exc_val, exc_tb)
        try:
            self.ring.teardown()
        except Exception as ee:
            LOG.error('Error tearing down: %r', ee)
        return False

    @asynccontextmanager
    async def open(self,
                   path,
                   flags: str,
                   mkdirs: bool = False) -> None:
        try:

            if self.rootdir is not None:
                path = self.rootdir / path.lstrip('/')
            else:
                path = Path(path)

            if mkdirs:
                path.parent.mkdir(parents=True, exist_ok=True)

            LOG.debug('Opening (%s) PosixFile: %s', flags, path)
            self.path = path
            self.fd = os.open(path, os_flags(flags)) # mode & ~umask

            self.offset = 0
            # fetch size
            self.size = os.fstat(self.fd).st_size
            
        except Exception as e:
            LOG.error('Error opening %s: %r', path, e)
            raise e

        try:
            yield self
        finally: # Closing
            # LOG.debug('Closing PosixFile: %s', id(self))
            try:
                if self.fd >= 0:
                    fd, self.fd = self.fd, -1
                    os.close(fd)
            except Exception as ee:
                LOG.error('Error closing %s: %r', path, ee)
                raise ee 


    async def read(self, size: int) -> bytes:
        """Reads n bytes from the current position/offset."""
        raise NotImplementedError("Use readinto")

    async def readinto(self, buffer: bytearray | memoryview) -> int:
        """
        Read up to *size* bytes from the source file directly into *buffer*.
        
        The kernel writes straight into the bytearray's memory — no
        intermediate allocation occurs (iovec on io_uring, memoryview on
        the executor path).
        
        Returns
        -------
        int
          Bytes actually read; 0 means EOF.
        """
        if self.fd < 0:
            raise RuntimeError("Not open — use as a context manager")
        fut = self.loop.create_future()      # asyncio.Future returning an int
        self.ring.submit_read(self.fd, buffer, self.offset, fut)
        n = await fut
        self.offset += n
        return n

    async def write(self, data: bytes | bytearray | memoryview) -> int:
        if self.fd < 0:
            raise RuntimeError("Not open — use as a context manager")
        n = len(data)
        # LOG.debug('Submit write: size: %s | offset: %s', n, self.dst_offset)
        fut = self.loop.create_future() # asyncio.Future returning None
        self.ring.submit_write(self.fd, data, self.offset, fut)
        w = await fut
        self.offset += w
        return w

    async def unlink(self, path) -> None:
        if self.rootdir is not None:
            path = self.rootdir / path.lstrip('/')
        else:
            path = Path(path)
        os.unlink(path)

    async def make_read_only(self) -> None:
        if self.fd < 0:
            raise RuntimeError("Not open — use as a context manager")
        # mode = os.fstat(self.fd).st_mode
        # os.fchmod(self.fd, mode & 0o444)
        os.fchmod(self.fd, 0o444) # umask does apply

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    import sys

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <conf> <src> <dst>")
        sys.exit(1)

    logging.basicConfig(level=logging.DEBUG,
                        format='%(message)s')

    from contextlib import AbstractAsyncContextManager
    from . import ProgressBar

    async def main(src, dst):

        os.umask(0o022)

        rctx = PosixStream()
        wctx = PosixStream(rootdir = 'tests')
        
        rfile = rctx.open(src, 'r')
        wfile = wctx.open(dst, 'w')

        async with rfile as r, wfile as w:

            LOG.debug("\tReader: %s", id(r))
            LOG.debug("\tWriter: %s", id(w))

            LOG.debug("Filesize: %s bytes", r.size)
            tracer = ProgressBar("Copying", r.size)

            #chunksize = max(r.CHUNK_SIZE, w.CHUNK_SIZE)
            chunksize = min(r.CHUNK_SIZE, w.CHUNK_SIZE)
            LOG.debug("Chunk size: %s bytes", chunksize)
            buffer = bytearray(chunksize)

            while True:
                n = await r.readinto(buffer)
                if n == 0:
                    break
                await w.write(buffer[:n])
                tracer.update(n)
            tracer.close()
            LOG.debug("Copied %s bytes / %s bytes", r.tell(), w.tell())
                    
            if r.size != w.tell():
                LOG.error("\tMissing bytes from: %s", src)


    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    #loop.set_debug(True)

    try:
        loop.run_until_complete(main(sys.argv[1], sys.argv[2]))
    except KeyboardInterrupt as e:
        print('')
        LOG.warning('Cancelled')
        sys.exit(1)
