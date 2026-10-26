"""
Async HTTP file I/O using aiohttp.

This module provides an async HTTP file connector that implements the FileBase interface.

Usage:
    rctx = HTTPFile(url='http://localhost:9000', login='...', password='...')
    with rctx:
        async with rctx.open(path, flags='r') as r:
            buffer = bytearray(8 * 1024 * 1024)
            while True:
                n = await r.buffer(buffer)
                if n == 0: break
                # process buffer[:n]
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import aiohttp

from . import FileBase

LOG = logging.getLogger(__name__)

class HTTPFile(FileBase):
    """
    Async HTTP file I/O using aiohttp.
    Sync context for settings, async context manager via open() for operations.
    """

    CHUNK_SIZE: int = 64 * 1024 * 1024  # 64MB, default

    def __init__(
        self,
        url: str,
        login: str,
        password: str,
        **session_kwargs
    ) -> None:
        """
        Initialize S3 file context with connection settings.
        """
        self.url = url
        self.login = login
        self.password = password
        self.session_kwargs = session_kwargs
        self._session = None


    def __enter__(self) -> "S3File":
        self._session = aiohttp.ClientSession(
            base_url=self.url,
            auth=aiohttp.BasicAuth(self.login, password=self.password),
            **self.session_kwargs
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._session:
            self._session.close()
            self._session = None
        return False

    @asynccontextmanager
    async def open(
        self,
        path: str,
        flags: Literal["r", "w"]
    ):
        """
        Async context manager for HTTP operations.
        Configures, creates client, starts operation, and yields self.
        """
        # Configure for this operation
        if not flags == 'r':
            raise NotImplementedError(f"mode {flags} is not supported (yet)")

        self.path = path.lstrip('/')
        self.flags = flags
        self.size: int = 0
        self.bytes_read: int = 0
        self._eof = False
        response = None

        # Create client
        async with aiohttp.ClientSession(
                base_url=self.url,
                auth=aiohttp.BasicAuth(self.login, password=self.password),
                **self.session_kwargs
        ) as client:
            try:

                # Fetch size
                response = await client.head(self.path)
                response.raise_for_status()
                self.size = int(response.headers.get('Content-Length', 0))
                LOG.debug("HTTP Reading %s/%s (size: %d)", self.url, self.path, self.size)

                response = await client.get(self.path)
                response.raise_for_status()
                self._response = response
                yield self

            finally: # clean up
                if response:
                    await response.release()
                self._response = None
                        
    async def read(self, size: int) -> bytes:
        """Reads n bytes from the current position/offset."""
        # LOG.debug('Calling read(%s)', size)
        b = bytearray(size)
        n = await self.readinto(b)
        return b[:n]

    def tell(self) -> int:
        return self.bytes_read

    async def readinto(self, buffer: bytearray | memoryview) -> int:
        """
        Read data from HTTP response into buffer.
        Only valid in read mode ("r").
        Returns the number of bytes read.
        """
        # LOG.debug('Calling readinto: bufsize: %s', len(buffer))
        if self.flags != "r":
            raise ValueError("readinto() only valid in read mode")
        if not self._response:
            raise RuntimeError("Not open — use as a context manager")
        if self._eof:
            return 0

        bytes_to_read = len(buffer)
        offset = 0

        while bytes_to_read > 0:
            chunk = await self._response.content.read(bytes_to_read)
            if not chunk:
                self._eof = True
                break

            chunk_len = len(chunk)
            buffer[offset:offset + chunk_len] = chunk
            offset += chunk_len
            bytes_to_read -= chunk_len
            self.bytes_read += chunk_len

        return offset

    async def write(self, data: bytes | bytearray | memoryview) -> int:
        raise NotImplementedError('HTTP connector does not support uploading (yet)')

    async def stat(self, path) -> dict:
        """Fetch object metadata."""
        return await self._session.head(path.lstrip('/'))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <src> <dst>")
        sys.exit(1)

    logging.basicConfig(level=logging.DEBUG,
                        format='%(name)s | %(message)s')

    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    from . import ProgressBar
    from .posix import PosixFile

    async def main(src, dst):

        rctx = HTTPFile(url = 'http://localhost:8443',
                        login = 'demo',
                        password = 'hello')
        wctx = PosixFile()
        
        with rctx, wctx:
            rfile = rctx.open(src, 'r')
            wfile = wctx.open(dst, 'w')

            async with rfile as r, wfile as w:

                # LOG.debug("\tReader: %s", id(r))
                # LOG.debug("\tWriter: %s", id(w))

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
                LOG.debug("Copied %s bytes / %s bytes", r.bytes_read, w.bytes_written)
                    
                if r.size != w.bytes_written:
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
