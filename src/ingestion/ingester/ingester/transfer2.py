"""
transfer.py — Async file I/O with automatic io_uring / executor fallback,
              reading from a local file *or* from S3.

Two transfer classes (pick one from your configuration)
-------------------------------------------------------
 AsyncTransfer(src, dst)                         disk  → disk
 AsyncS3Transfer(bucket, key, dst, client=s3)    S3    → disk

Both share the same interface (readinto / write / src_seek / dst_seek /
src_size / bytes_read / bytes_written) so the code that processes chunks
doesn't care which one it was handed.  The destination is always a local
file.

AsyncS3Transfer is natively async (aiobotocore / aiohttp): no thread is
parked per read.  It issues a single ranged GET and streams the body into
your buffer; on seek or on a dropped connection it transparently re-opens
the stream with a new Range header, pinned to the object's ETag (If-Match)
so a mid-transfer overwrite of the object fails loudly instead of producing
a Frankenstein file.  The S3 client is created by *you*, once, and shared
(see below).

   pip install aiobotocore        # only needed for AsyncS3Transfer

Backend selection for local-file I/O (at import time)
-----------------------------------------------------
 1. Try to import liburing and probe the kernel with a real queue_init call.
    If both succeed  →  _Ring     (io_uring backend, Linux ≥ 5.1)
 2. Otherwise        →  _RingFallback  (ThreadPoolExecutor backend,
                         works on macOS, old kernels, Docker-on-Mac, …)

The two backends share the same _RingBase interface so AsyncTransfer is
completely unaware of which one is active.  A module-level constant
_BACKEND ('io_uring' | 'executor') exposes the selection to callers.

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
                 │  thread: os.preadv(fd, [mv])    │
                 │  thread: os.pwritev(fd, [data]) │
                 └─────────────────────────────────┘

Usage
-----
   buffer = bytearray(64 * 1024)

   # disk → disk
   async with AsyncTransfer("src.bin", "dst.bin") as t:
       ...

   # S3 → disk.  Create the client ONCE (per process / event loop) and reuse
   # it for every file: it owns the aiohttp connection pool, TLS sessions and
   # credential cache.
   from aiobotocore.session import get_session
   from aiobotocore.config import AioConfig

   async with get_session().create_client(
           's3', endpoint_url=...,
           config=AioConfig(max_pool_connections=32)) as s3:   # ≥ concurrent transfers
       async with AsyncS3Transfer("bucket", "some/key", "dst.bin", client=s3) as t:
           print(t.src_size)
           while True:
               n = await t.readinto(buffer)
               if n == 0:
                   break
               process(buffer[:n])           # transform in-place
               await t.write(buffer[:n])

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

from abc import ABC, abstractmethod

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

   readinto uses os.preadv(fd, [memoryview(buffer)[:size]], offset) so the OS
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
       # Slice to `size` so we honour the caller's limit, like the io_uring path.
       view = memoryview(buffer)[:size]
       self._chain(self.loop.run_in_executor(self.pool, os.preadv, fd, [view], offset), fut)

   def submit_write(
       self, fd: int, data: bytes | bytearray | memoryview, size: int,
       offset: int, fut: asyncio.Future,
   ) -> None:

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


# ---------------------------------------------------------------------------
# Sources — where the bytes come from (local file, S3)
# ---------------------------------------------------------------------------

class _SourceBase(ABC):
   """
   A random-access, async byte source.  `readinto` is positional (explicit
   offset) so AsyncTransfer owns the cursor and seeking is just arithmetic.
   """

   size: int = 0       # total size in bytes, valid after open()

   @abstractmethod
   async def open(self) -> None: ...

   @abstractmethod
   async def close(self) -> None: ...

   @abstractmethod
   async def readinto(self, buffer: bytearray, size: int, offset: int) -> int:
      """Fill buffer[:size] from `offset`.  Returns bytes read; 0 means EOF."""


class _FileSource(_SourceBase):
   """Local file, read through the ring (io_uring or executor)."""

   def __init__(self, path, flags: int, ring: _RingBase,
                loop: asyncio.AbstractEventLoop) -> None:
      self.path  = path
      self.flags = flags
      self.ring  = ring
      self.loop  = loop
      self.fd    = -1

   async def open(self) -> None:
      self.fd   = os.open(self.path, self.flags)
      self.size = os.fstat(self.fd).st_size

   async def close(self) -> None:
      if self.fd >= 0:
         fd, self.fd = self.fd, -1
         os.close(fd)

   async def readinto(self, buffer: bytearray, size: int, offset: int) -> int:
      if self.fd < 0:
         raise RuntimeError("Not open — use as a context manager")
      fut = self.loop.create_future()      # asyncio.Future returning an int
      self.ring.submit_read(self.fd, buffer, size, offset, fut)
      return await fut


class _S3Source(_SourceBase):
   """
   S3 object, streamed with aiobotocore.

   One ranged GET stays open and is consumed sequentially.  If the requested
   offset isn't where the stream currently is (seek), or the connection drops
   mid-read, the stream is re-opened with `Range: bytes=<offset>-`.

   The client is owned by the caller and is never closed here.
   """

   MAX_RETRIES = 5

   def __init__(self, bucket: str, key: str, client) -> None:
      self.bucket = bucket
      self.key    = key
      self._client = client
      self._etag: str | None = None
      self._body = None                        # aiobotocore StreamingBody
      self._pos  = 0                           # next byte the open stream will yield
      self._retryable: tuple = ()

   async def open(self) -> None:
      import aiohttp
      from botocore.exceptions import BotoCoreError

      # Transient network failures → reopen the stream and carry on.
      # botocore's ClientError (404, 412, 403, …) is deliberately NOT here.
      self._retryable = (aiohttp.ClientError, asyncio.TimeoutError,
                         ConnectionError, BotoCoreError)

      head = await self._client.head_object(Bucket=self.bucket, Key=self.key)
      self.size  = head['ContentLength']
      self._etag = head['ETag']

   async def close(self) -> None:
      self._close_stream()
      self._etag = None

   # ------------------------------------------------------------------

   def _close_stream(self) -> None:
      if self._body is not None:
         body, self._body = self._body, None
         try:
            body.close()                       # drops the connection if unread
         except Exception:
            pass

   async def _open_stream(self, offset: int) -> None:
      self._close_stream()
      resp = await self._client.get_object(
         Bucket=self.bucket, Key=self.key,
         Range=f'bytes={offset}-',
         IfMatch=self._etag,                   # object changed under us → 412
      )
      self._body = resp['Body']
      self._pos  = offset

   async def readinto(self, buffer: bytearray, size: int, offset: int) -> int:
      if self._etag is None:
         raise RuntimeError("Not open — use as a context manager")
      size = min(size, self.size - offset)
      if size <= 0:
         return 0                              # EOF (also avoids 416 on empty objects)

      view   = memoryview(buffer)
      filled = 0
      failures = 0
      while filled < size:
         try:
            if self._body is None or self._pos != offset + filled:
               await self._open_stream(offset + filled)
            # StreamingBody.read(n) may return fewer than n bytes, so loop.
            chunk = await self._body.read(size - filled)
            if not chunk:
               raise ConnectionResetError(
                  f"S3 stream ended early at byte {self._pos}/{self.size}")
         except self._retryable as exc:
            failures += 1
            if failures > self.MAX_RETRIES:
               raise
            LOG.warning("S3 read failed at byte %d (%s: %s), retry %d/%d",
                        offset + filled, type(exc).__name__, exc,
                        failures, self.MAX_RETRIES)
            self._close_stream()
            await asyncio.sleep(min(0.1 * 2 ** failures, 5.0))
            continue
         failures = 0
         view[filled:filled + len(chunk)] = chunk     # the one unavoidable copy
         filled   += len(chunk)
         self._pos += len(chunk)
      return filled


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _resolve_seek(current: int, size: int, offset: int, whence: int) -> int:
   if whence == os.SEEK_SET:
      new = offset
   elif whence == os.SEEK_CUR:
      new = current + offset
   elif whence == os.SEEK_END:
      new = size + offset
   else:
      raise ValueError(f"invalid whence: {whence}")
   if new < 0:
      raise ValueError("negative seek position")
   return new


class _TransferBase:
   """
   Shared plumbing: the destination file, the ring, the cursors and the
   async context manager.  Subclasses only decide where the bytes come from
   by setting ``self._src`` in their __init__.
   """

   _src: _SourceBase

   def __init__(self, dst) -> None:
      self.loop = asyncio.get_running_loop()
      self.dst = dst

      self.dst_fd: int = -1
      self.ring: _RingBase = _Ring()  # io_uring or fallback, decided above
      self._ring_ready = False

      self.src_offset:  int = 0
      self.dst_offset: int = 0

      self.bytes_read:    int = 0
      self.bytes_written: int = 0

      self.dst_flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC

   @property
   def src_size(self) -> int:
      """Total source size in bytes (valid once the context is entered)."""
      return self._src.size

   # ------------------------------------------------------------------
   # Context manager
   # ------------------------------------------------------------------

   async def __aenter__(self):
      try:
         await self._src.open()
         if self.dst:
            self.dst_fd = os.open(self.dst, self.dst_flags, 0o666) # 666 & ~umask
         self.ring.setup(self.loop)
         self._ring_ready = True
      except BaseException:
         # __aexit__ is not called when __aenter__ raises; don't leak the
         # S3 stream / fds (S3 open is a network call, so this can fail).
         await self._close_all()
         raise
      return self

   async def __aexit__(self, exc_type, exc_val, exc_tb):
      errors = await self._close_all()
      if errors and exc_type is None:
         raise errors[0] # first one
      return False

   async def _close_all(self) -> list:
      errors = []
      if self._ring_ready:
         self._ring_ready = False
         try:
            self.ring.teardown()
         except Exception as e:
            errors.append(e)
      try:
         await self._src.close()
      except Exception as e:
         errors.append(e)
      if self.dst_fd >= 0:
         try:
            os.close(self.dst_fd)
         except OSError as e:
            errors.append(e)
         self.dst_fd = -1
      return errors

   # ------------------------------------------------------------------
   # I/O
   # ------------------------------------------------------------------

   async def readinto(self, buffer: bytearray, size = None) -> int:
      """
      Read up to *size* bytes from the source directly into *buffer*.

      Disk: the kernel writes straight into the bytearray's memory
      (iovec on io_uring, memoryview on the executor path).
      S3: bytes are copied once from the HTTP stream into the buffer.

      Returns
      -------
      int
          Bytes actually read; 0 means EOF.  Short reads only happen at EOF
          for S3; local files may return short reads like pread().
      """
      if not self._ring_ready:
         raise RuntimeError("Not open — use as a context manager")
      _size = len(buffer)
      if size is not None:
         _size = min(size, _size)

      # LOG.debug('Submit read: size: %s | offset: %s', _size, self.src_offset)

      n = await self._src.readinto(buffer, _size, self.src_offset)
      self.src_offset += n
      self.bytes_read  += n
      return n

   async def write(self, data: bytes | bytearray | memoryview) -> None:
      """
      Write *data* to the destination file.

      On the io_uring path the kernel reads directly from the bytearray /
      memoryview memory (no copy for mutable types).
      """
      if self.dst is None:
         return

      if self.dst_fd < 0:
         raise RuntimeError("Not open — use as a context manager")
      n = len(data)

      # LOG.debug('Submit write: size: %s | offset: %s', n, self.dst_offset)

      fut = self.loop.create_future() # asyncio.Future returning an int
      self.ring.submit_write(self.dst_fd, data, n, self.dst_offset, fut)
      await fut
      self.dst_offset += n
      self.bytes_written += n

   # no need for async
   def src_seek(self, offset, whence = os.SEEK_SET) -> int:
      self.src_offset = _resolve_seek(self.src_offset, self._src.size, offset, whence)
      return self.src_offset

   def dst_seek(self, offset, whence = os.SEEK_SET) -> int:
      size = os.fstat(self.dst_fd).st_size if whence == os.SEEK_END else 0
      self.dst_offset = _resolve_seek(self.dst_offset, size, offset, whence)
      return self.dst_offset


class AsyncTransfer(_TransferBase):
   """
   Disk → disk, chunk by chunk, as an async context manager.

   Uses io_uring on Linux ≥ 5.1 with liburing installed, or falls back to a
   ThreadPoolExecutor automatically.  Check ``_BACKEND`` to see which is
   active.

   Parameters
   ----------
   src : str | Path
       Source file path.
   dst : str | Path | None
       Destination file path (created / truncated).  None = discard writes.
   direct, nonblock : bool
       Extra open flags (O_DIRECT / O_NONBLOCK) for source and destination.
   """

   def __init__(self, src, dst, *, direct: bool = False, nonblock: bool = False) -> None:
      super().__init__(dst)
      self.src = os.fspath(src)

      src_flags = os.O_RDONLY

      # O_NONBLOCK so the event loop can register the fds.
      # On regular files the kernel ignores O_NONBLOCK for actual I/O, but
      # the flag is required for add_reader / add_writer to function.
      if nonblock:
         src_flags |= os.O_NONBLOCK
         self.dst_flags |= os.O_NONBLOCK

      # We don't use O_DIRECT because it's likely a network-ed filesystem, like Ceph/NFS
      if direct:
         src_flags |= os.O_DIRECT
         self.dst_flags |= os.O_DIRECT

      self._src = _FileSource(self.src, src_flags, self.ring, self.loop)
      LOG.debug('Using backend: %s | source: disk', _BACKEND)


class AsyncS3Transfer(_TransferBase):
   """
   S3 → disk, chunk by chunk, as an async context manager.

   Parameters
   ----------
   bucket, key : str
       The object to read.
   dst : str | Path | None
       Destination file path (created / truncated).  None = discard writes.
   client : aiobotocore S3 client
       Created by the caller with ``get_session().create_client('s3', ...)``
       and shared across transfers.  Never closed by this class.  The
       client is bound to the event loop it was created on.
   """

   def __init__(self, bucket: str, key: str, dst, *, client) -> None:
      super().__init__(dst)
      self.src = f"s3://{bucket}/{key}"
      self._src = _S3Source(bucket, key, client)
      LOG.debug('Using backend: %s | source: s3', _BACKEND)


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

class ProgressTracer(TracerBase):

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
                width=None, fill='█', scale = 1<<20, unit = 'MB/s'):
      self.desc = desc or ''
      self.total = size
      self.progress = 0
      self.fill = fill
      self.start_time = time.time()
      self.scale = scale or None
      self.unit = unit or 'it/s' # iterations per seconds
      self.line_fmt = '\r' + self.desc + '|{bar}| {percent:.1f}% {speed:6.2f} ' + unit

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
      sys.stderr.flush()

   def update(self, n):
      self.progress += n
      self.print_line()

   def close(self):
      print('', file=sys.stderr) # extra new line
      sys.stderr.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":

   args = sys.argv[1:]
   use_s3 = '--s3' in args
   args = [a for a in args if a != '--s3']

   if not args:
      print(f"Usage: {sys.argv[0]} <src> [dst]")
      print(f"       {sys.argv[0]} --s3 <bucket>/<key> [dst]")
      print("  S3_ENDPOINT_URL=http://localhost:9000  for MinIO / Ceph RGW")
      sys.exit(1)

   logging.basicConfig(level=logging.DEBUG,
                       format='%(message)s')

   async def copy(t):
      filesize = t.src_size
      LOG.debug("Filesize: %s", filesize)

      tracer = ProgressBar("Copying", filesize)
      if os.getenv('NO_TRACER', None) == '1':
         tracer = NoTracer("Copying", filesize)

      chunk_size = 1<<23 # 8 MB
      buffer = bytearray(chunk_size)

      while True:
         n = await t.readinto(buffer)
         if n == 0:
            break
         await t.write(buffer[:n])
         tracer.update(n)
      tracer.close()
      LOG.debug("copied: %s -> %s bytes", t.bytes_read, t.bytes_written)

   async def main(src, dst):
      if not use_s3:
         async with AsyncTransfer(src, dst) as t:
            await copy(t)
         return

      from aiobotocore.session import get_session
      bucket, _, key = src.partition('/')
      kwargs = {}
      if os.getenv('S3_ENDPOINT_URL'):
         kwargs['endpoint_url'] = os.environ['S3_ENDPOINT_URL']
      async with get_session().create_client('s3', **kwargs) as s3:
         async with AsyncS3Transfer(bucket, key, dst, client=s3) as t:
            await copy(t)

   loop = asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   #loop.set_debug(True)
   loop.run_until_complete(main(args[0], args[1] if len(args) > 1 else None))
