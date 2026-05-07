"""
transfer.py — Async file I/O with automatic io_uring / executor fallback.

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
   buffer = bytearray(64 * 1024)

   async with AsyncTransfer("src.bin", "dst.bin") as t:
       while True:
           n = await t.readinto(buffer)
           if n == 0:
               break
           process(buffer[:n])           # transform in-place
           await t.write(buffer[:n])

   print(BACKEND)        # 'io_uring' or 'executor'

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
import sys
import time
import itertools

from abc import ABC, abstractmethod
from collections.abc import Iterable

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
   from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Abstract base — the interface AsyncTransfer talks to
# ---------------------------------------------------------------------------

class _RingBase(ABC):
   @abstractmethod
   def setup(self, loop: asyncio.AbstractEventLoop) -> None: ...

   @abstractmethod
   def teardown(self) -> None: ...

   @abstractmethod
   def submit_read(
       self, fd: int, buffer: bytearray, size: int, offset: int,
       fut: asyncio.Future,
   ) -> None: ...

   @abstractmethod
   def submit_write(
       self, fd: int, data: bytes | bytearray | memoryview, size: int,
       offset: int, fut: asyncio.Future,
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

   def __init__(self):
      self.ring = _lu.io_uring()
      self.efd  = -1
      self.pending: dict[int, asyncio.Future] = {}
      self.token_counter = 0
      self.loop = None

   def setup(self, loop):
      _liburing.trap_error(_liburing.io_uring_queue_init(self.QUEUE_DEPTH, self.ring, 0))
      
      self.efd = os.eventfd(0, os.EFD_NONBLOCK)
      _liburing.trap_error(_liburing.io_uring_register_eventfd(self.ring, self.efd))

      loop.add_reader(self.efd, self._on_cqe_ready)
      self.loop = loop

   def teardown(self) -> None:
      if self.loop is not None:
         try:
            self.loop.remove_reader(self.efd)
         except Exception:
            pass
      if self.efd >= 0:
         os.close(self.efd)
         self.efd = -1
      _liburing.io_uring_queue_exit(self.ring)

   # ------------------------------------------------------------------

   def _next_token(self) -> int:
      self.token_counter = (self.token_counter + 1) & 0xFFFF_FFFF_FFFF_FFFF
      return self.token_counter

   def submit_read(
         self, fd: int, buffer: bytearray, size: int, offset: int,
         fut: asyncio.Future,
   ) -> None:
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

   def __init__(self):
      self.pool = None
      self.loop = None

   def setup(self, loop):
      self.loop = loop
      self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="async_xfer")

   def teardown(self):
      if self.pool:
         self.pool.shutdown(wait=False)
         self.pool = None

   # ------------------------------------------------------------------

   def submit_read(
       self, fd: int, buffer: bytearray, size: int, offset: int,
       fut: asyncio.Future,
   ) -> None:

       self._chain(self.loop.run_in_executor(self.pool, os.preadv, fd, [buffer], offset), fut)

   def submit_write(
       self, fd: int, data: bytes | bytearray | memoryview, size: int,
       offset: int, fut: asyncio.Future,
   ) -> None:

      self._chain(self.loop.run_in_executor(self.pool, os.pwritev, fd, [data], offset), fut)

   # def submit_write(
   #     self, fd: int, data: bytes | bytearray | memoryview, size: int,
   #     offset: int, fut: asyncio.Future,
   # ) -> None:
   #     # Capture a bytes snapshot so the caller can safely reuse `data`
   #     # immediately after submit_write returns (before the thread runs).
   #     snapshot = bytes(data) if not isinstance(data, bytes) else data

   #     def _do() -> None:
   #         os.pwrite(fd, snapshot, offset)

   #     self._chain(self.loop.run_in_executor(self.pool, _do), fut)

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


# ---------------------------------------------------------------------------
# Public API  (unchanged regardless of backend)
# ---------------------------------------------------------------------------

class AsyncTransfer:
   """
   Async context manager for chunk-by-chunk file transfer.

   Uses io_uring on Linux ≥ 5.1 with liburing installed, or falls back
   to a ThreadPoolExecutor automatically.  Check ``_BACKEND``
   to see which is active.

   Parameters
   ----------
   src : str | Path
       Source file path.
   dst : str | Path
       Destination file path (created / truncated).
   chunk_size : int
       Default read size when ``readinto`` is called without an explicit size.
   """

   def __init__(self, src, dsts: str | list[str] | set[str] = None,
                *,
                direct: bool = False,
                nonblock: bool = False,
                excl: bool = True,
                fsync: bool = True
                ) -> None:
      self.loop = asyncio.get_running_loop()
      self.src = src
      dsts = dsts or [] # None becomes []
      if isinstance(dsts, str):
         self.dsts = [dsts]
      else: # let it fail on bytes
         assert isinstance(dsts, Iterable)
         self.dsts = list(set(dsts)) # remove duplicates
      
      self.src_fd: int = -1
      self.dst_fds = [-1 for _ in self.dsts]
      self.ring: _RingBase = _Ring()  # io_uring or fallback, decided above
      
      self.src_offset:  int = 0
      self.dst_offsets = [0 for _ in self.dsts]
      
      self.bytes_read:    int = 0
      self.bytes_written = [0 for _ in self.dsts]
      
      self.src_flags = os.O_RDONLY
      self.dst_flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC

      # O_NONBLOCK so the event loop can register the fds.
      # On regular files the kernel ignores O_NONBLOCK for actual I/O, but
      # the flag is required for add_reader / add_writer to function.
      if nonblock:
         self.src_flags |= os.O_NONBLOCK
         self.dst_flags |= os.O_NONBLOCK
      
      # We don't use O_DIRECT because it's likely a network-ed filesystem, like Ceph/NFS
      if direct:
         self.src_flags |= os.O_DIRECT
         self.dst_flags |= os.O_DIRECT

      if excl:
         self.dst_flags |= os.O_EXCL
      
      self.fsync = fsync

      LOG.debug('Using backend: %s', _BACKEND)


   # ------------------------------------------------------------------
   # Context manager
   # ------------------------------------------------------------------

   async def __aenter__(self):
      self.src_fd = os.open(self.src, self.src_flags)
      for i, dst in enumerate(self.dsts):
         self.dst_fds[i] = os.open(dst, self.dst_flags, 0o666) # 666 & ~umask
      self.ring.setup(self.loop)
      return self

   async def __aexit__(self, exc_type, exc_val, exc_tb):
      self.ring.teardown()
      errors = []
      for fd in itertools.chain([self.src_fd], self.dst_fds):
         if fd >= 0:
            try:
               if self.fsync:
                  os.fsync(fd)
               os.close(fd)
            except OSError as e:
               errors.append(e)
      self.dsts_fd = [-1 for _ in self.dsts]
      if errors and exc_type is None:
         raise errors[0] # first one
      return False

   # ------------------------------------------------------------------
   # I/O
   # ------------------------------------------------------------------

   async def readinto(self, buffer: bytearray, size = None) -> int:
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
      if self.src_fd < 0:
         raise RuntimeError("Not open — use as a context manager")
      _size = len(buffer)
      if size is not None:
         _size = min(size, _size)
         
      # LOG.debug('Submit read: size: %s | offset: %s', _size, self.src_offset)

      fut = self.loop.create_future() # asyncio.Future returning an int
      self.ring.submit_read(self.src_fd, buffer, _size, self.src_offset, fut)
      n = await fut
      self.src_offset += n
      self.bytes_read  += n
      return n

   async def write(self, data: bytes | bytearray | memoryview) -> None:
      """
      Write *data* to the destination file.

      On the io_uring path the kernel reads directly from the bytearray /
      memoryview memory (no copy for mutable types).
      """
 
      n = len(data)

      for i, fd in enumerate(self.dst_fds):
         if fd < 0:
            raise RuntimeError("Not open — use as a context manager")
      
         # LOG.debug('Submit write: size: %s | offset: %s', n, self.dst_offset)
      
         fut = self.loop.create_future() # asyncio.Future returning None
         self.ring.submit_write(fd, data, n, self.dst_offsets[i], fut)
         await fut
         self.dst_offsets[i] += n
         self.bytes_written[i] += n
         
   # no need for async
   def src_seek(self, offset, whence = os.SEEK_SET) -> int:
      self.src_offset = os.lseek(self.src_fd, offset, whence)

   def dsts_seek(self, offset, whence = os.SEEK_SET) -> int:
      for i, fd in enumerate(self.dst_fds):
         self.dst_offsets[i] = os.lseek(fd, offset, whence)


# ---------------------------------------------------------------------------
# Progress Bar
# ---------------------------------------------------------------------------

class TracerBase():

   def __init__(self, desc: str, size: int):
      self.size = size
      self.desc = desc

   @abstractmethod
   def update(self, n: int) -> None: ...

   @abstractmethod
   def close(self) -> None: ...

class NoTracer(TracerBase):

   def update(self, n: int):
      pass

   def close(self):
      pass

class TQDMTracer(TracerBase):

   def __new__(cls, value):
      from tqdm import tqdm
      return super().__new__(cls)
        
   def __init__(self, desc: str, size: int):
      super().__init__(desc, size)
      self._tracer = tqdm(total=self.size,
                          unit='B',
                          unit_divisor=1024,
                          unit_scale=True,
                          bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]',
                          desc=self.desc)

   def update(self, n: int):
      self._tracer.update(n)

   def close(self):
      self._tracer.close()

class ProgressBar(TracerBase):

   default_width = 30

   def __init__(self, desc, size,
                width=None, fill='█', scale = 1<<20, unit = 'MB/s', flush = False):
      self.desc = desc or ''
      self.total = size
      self.progress = 0
      self.fill = fill
      self.start_time = time.time()
      self.scale = scale or None
      self.unit = unit or 'it/s' # iterations per seconds
      self.line_fmt = '\r' + self.desc + '|{bar}| {percent:.1f}% {speed:6.2f} ' + unit
      self.flush = flush
      
      if width is not None:
         self.width = width
      else:
         try:
            import shutil
            terminal_width = shutil.get_terminal_size().columns
         except:
            terminal_width = self.default_width
         # Calculate space needed for prefix, percent, and speed
         extra_left = len(self.desc) + 1 # for the |
         extra_right = len(f"| 100.0% 123456.78 {unit}")
         margin = extra_left + extra_right
         self.width = max(self.default_width,
                          terminal_width - margin) # Ensure minimum bar length of 30
            

   def print_line(self):
      percent = (100 * self.progress) / self.total
      w = (self.width * self.progress) // self.total
      bar = self.fill * w + '-' * (self.width - w)

      # Calculate speed (items/second)
      elapsed = time.time() - self.start_time
      speed = self.progress / elapsed if elapsed > 0 else 0
      if self.scale:
         speed = speed / self.scale
         
      # Format the line
      line = self.line_fmt.format(bar = bar, percent=percent, speed=speed)
      print(line, end='', file=sys.stderr)
      if self.flush:
         sys.stderr.flush()

   def update(self, n):
      self.progress += n
      self.print_line()

   def close(self):
      print('', file=sys.stderr) # extra new line
      if self.flush:
         sys.stderr.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":

   if len(sys.argv) < 2:
      print(f"Usage: {sys.argv[0]} <src> [dst1,dst2,dst3]")
      sys.exit(1)

   logging.basicConfig(level=logging.DEBUG,
                       format='%(message)s')


   async def main(src, dsts):

      filesize = os.stat(src).st_size
      LOG.debug("Filesize: %s bytes", filesize)

      chunk_size = 1<<23 # 8 MB
      #chunk_size = 1<<26 # 64 MB
      buffer = bytearray(chunk_size)

      tracer = ProgressBar("Copying", filesize)
      if os.getenv('NO_TRACER', None) == '1':
         tracer = NoTracer("Copying", filesize)

      async with AsyncTransfer(src, dsts) as t:
         while True:
            n = await t.readinto(buffer)
            if n == 0:
               break
            await t.write(buffer[:n])
            tracer.update(n)
         tracer.close()

         LOG.debug("%s: %s bytes / %s bytes", "Copied" if dsts else "Read", t.bytes_read, filesize)
            
         if filesize != t.bytes_read:
            LOG.error("\tMissing bytes from: %s", src)
         else:
            for i, w in enumerate(t.bytes_written):
               if t.bytes_read != w:
                  LOG.error("\t* Missing bytes on dst%s: %s", i, dsts[i])
                  LOG.error("\t  Copied %s bytes and should be %s", w, t.bytes_read)


   loop = asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   #loop.set_debug(True)

   try:
      loop.run_until_complete(main(sys.argv[1], sys.argv[2:])) # graceful degradation
   except KeyboardInterrupt as e:
      print('')
      LOG.warning('Cancelled')
      sys.exit(1)

