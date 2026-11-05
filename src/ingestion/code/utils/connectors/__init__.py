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



def load(section: dict, **kwargs):
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
      case 'http':
         from .http import HTTPStream
         return HTTPStream(section['url'], # fail if missing
                           section['login'],
                           section['password'],
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

