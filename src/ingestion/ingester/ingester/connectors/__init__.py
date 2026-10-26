import sys
import time
from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager

__all__ = ['FileBase', 'load', 'NoTracer', 'ProgressBar']


class FileBase(ABC):
   """
   A async byte stream source/destination.
   """

   size: int = 0              # total size in bytes, valid after open()
   CHUNK_SIZE: int = 1 << 23  # 8MB, default: 8 * 1024 * 1024

   @abstractmethod
   def __enter__(self) -> None: ...

   @abstractmethod
   def __exit__(self, exc_type, exc_val, exc_tb) -> bool: ...

   @abstractmethod
   async def open(self,
                  path: str,
                  flags: str,
                  mkdirs: bool = False) -> AbstractAsyncContextManager: ...

   @abstractmethod
   async def readinto(self, buffer: bytearray | memoryview, offset: int) -> int:
      """Fill buffer[:size] from `offset`. Returns bytes read; 0 means EOF."""

   @abstractmethod
   async def read(self, size: int) -> bytes:
      """Reads n bytes from the current position/offset."""

   @abstractmethod
   async def write(self, buffer: bytes | bytearray | memoryview, offset: int) -> int:
      """Writes buffer (at `offset` if not None). Returns bytes written"""

   # @abstractmethod
   # async def seek(self, offset: int, whence: int) -> int:
   #    """Set the current position of the file to position pos, modified by whence.
   #       Returns the new position in bytes relative to the start of the file."""

   @abstractmethod
   def tell(self) -> int:
      """Returns the current position in bytes relative to the start of the file."""
 
   # Not async, and only in posix interface
   async def unlink(self, path) -> None:
      raise NotImplementedError('unlink not implemented in this connector')



def load(section: dict, shared_with: FileBase = None, **kwargs):
   s = section['type']
   match s:
      case 'posix':
         from .posix import PosixFile
         if shared_with is not None and isinstance(shared_with, PosixFile):
            return PosixFile.build_from(shared_with, rootdir=section.get('rootdir'), **kwargs)
         return PosixFile(rootdir=section.get('rootdir'), **kwargs)
      # case 'sftp':
      #    from .sftp import SFTPFile
      #    if shared_with is not None and isinstance(shared_with, SFTPFile):
      #       return SFTPFile.build_from(shared_with,
      #                                  section['host'], # fail if missing
      #                                  section['username'], # fail if missing
      #                                  port=section.get('port'),
      #                                  password=section.get('password'),
      #                                  private_key=section.get('private_key'),
      #                                  passphrase=section.get('passphrase'),
      #                                  **kwargs)

      #    return SFTPFile(section['host'], # fail if missing
      #                    section['username'], # fail if missing
      #                    port=section.get('port'),
      #                    password=section.get('password'),
      #                    private_key=section.get('private_key'),
      #                    passphrase=section.get('passphrase'),
      #                    **kwargs)
      case 's3':
         from .s3 import S3File
         return S3File(section['endpoint'], # fail if missing
                       section['bucket'], # fail if missing
                       access_key=section.get('access_key'),
                       secret_key=section.get('secret_key'),
                       session_token=section.get('session_token'),
                       signature_version=section.get('signature_version'),
                       region=section.get('region'),
                       **kwargs)
      case 'http':
         from .http import HTTPFile
         return HTTPFile(section['url'], # fail if missing
                         section['login'],
                         section['password'],
                         **kwargs)
      case _:
         raise ValueError(f"Unknown connector: {s}")



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
