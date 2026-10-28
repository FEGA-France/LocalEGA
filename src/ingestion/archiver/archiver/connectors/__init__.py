import sys
import time
from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager, asynccontextmanager

__all__ = ['FileStream', 'NoContext', 'noop', 'load', 'NoTracer', 'ProgressBar']

class FileStream(ABC):
   """
   A async byte stream.
   """
   
   size: int = 0              # total size in bytes, valid after open()
   offset: int = 0            # position
   CHUNK_SIZE: int = 1 << 23  # 8MB, default: 8 * 1024 * 1024

   @abstractmethod
   def __enter__(self) -> "FileStream": ...

   @abstractmethod
   def __exit__(self, exc_type, exc_val, exc_tb) -> bool: ...

   @abstractmethod
   async def readinto(self, buffer: bytearray | memoryview) -> int:
      """Fills buffer, reading from `offset`. Returns bytes read; 0 means EOF."""

   @abstractmethod
   async def open(self,
                  path: str,
                  flags: str,
                  mkdirs: bool = False) -> AbstractAsyncContextManager: ...
         
   @abstractmethod
   async def readinto(self, buffer: bytearray | memoryview) -> int:
      """Fills buffer, reading from `offset`. Returns bytes read; 0 means EOF."""

   @abstractmethod
   async def read(self, size: int) -> bytes:
      """Reads n bytes from the current position/offset."""

   @abstractmethod
   async def write(self, buffer: bytes | bytearray | memoryview) -> int:
      """Writes buffer (at `offset` if not None). Returns bytes written"""
      
   def tell(self) -> int:
      """Returns the current position in bytes relative to the start of the file."""
      return self.offset
   
   @abstractmethod
   async def unlink(self, path) -> None:
      """Removes the file `path`."""

   @abstractmethod
   async def make_read_only(self) -> None: ...



def load(section: dict, shared_with: FileStream = None, **kwargs):
   s = section['type']
   match s:
      case 'posix':
         from .posix import PosixStream
         return PosixStream(rootdir=section.get('rootdir'), **kwargs)
      case 's3':
         from .s3 import S3Stream
         return S3Stream(section['endpoint'], # fail if missing
                         section['bucket'], # fail if missing
                         access_key=section.get('access_key'),
                         secret_key=section.get('secret_key'),
                         session_token=section.get('session_token'),
                         signature_version=section.get('signature_version'),
                         region=section.get('region'),
                         **kwargs)
      case _:
         raise ValueError(f"Unknown connector: {s}")

class NoContext():
   def __enter__(self):
      return None
   def __exit__(self, exc_type, exc_val, exc_tb):
      return False

@asynccontextmanager
async def noop(*args, **kwargs):
    yield None

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


