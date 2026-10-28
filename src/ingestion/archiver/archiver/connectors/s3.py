"""
Async S3 file I/O using aioboto3.

This module provides an async S3 file connector that implements the FileBase interface.

Usage:
    wctx = S3File(endpoint='localhost:9000', access_key='...', secret_key='...')
    with wctx:
        async with wctx.open(bucket, key, mode='w') as w:
            await w.write(data)
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError


from . import FileStream

LOG = logging.getLogger(__name__)

class S3Stream(FileStream):
    """
    Async S3 file I/O using aioboto3.
    Sync context for settings, async context manager via open() for operations.
    """

    # CHUNK_SIZE: int = 8 * 1024 * 1024  # 8MB, default

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key: str | None = None,
        secret_key: str | None = None,
        session_token: str | None = None,
        signature_version: str | None = None,
        region: str | None = None,
        **session_kwargs,
    ) -> None:
        """
        Initialize S3 file context with connection settings.
        """
        self.endpoint = endpoint
        assert '/' not in bucket, "bucket can't contain '/'"
        self.bucket = bucket
        self.config = Config(signature_version=signature_version or "s3v4")
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=session_token,
            region_name=region or 'us-east-1',
            **session_kwargs,
        )

    def __str__(self):
        return f'<S3Stream | endpoint:{self.endpoint} | bucket: {self.bucket}>' 

    def __enter__(self) -> "S3Stream":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    @asynccontextmanager
    async def open(
        self,
        path: str,
        flags: Literal["r", "w"]
    ):
        """
        Async context manager for S3 operations.
        Configures, creates client, starts operation, and yields self.
        """
        # Configure for this operation
        self.path = path.lstrip('/')
        assert not('r' in flags and 'w' in flags), f"Invalid mode {flags}"
        self.flags = flags

        # Reset state
        self._multipart_upload_id: str | None = None
        self._parts: list[dict] = []
        self._position: int = 0
        self._file_size: int = 0
        self._etag: str | None = None
        self._eof: bool = False

        # Public attributes
        self.size: int = 0
        self.bytes_read: int = 0
        self.bytes_written: int = 0


        # Create client
        async with self._session.client("s3",
                                        endpoint_url=self.endpoint,
                                        config=self.config,
                                        ) as s3_client:
            self._s3_client = s3_client  # Store reference for use in methods

            # Start operation
            if "r" in self.flags:
                await self._start_download()
            elif "w" in self.flags:
                await self._start_upload()
                
            try:
                yield self
            finally:
                # Stop operation
                if self.flags == "r":
                    await self._stop_download()
                elif self.flags == "w":
                    await self._stop_upload()

            # remove referernce
            self._s3_client = None
                        
        # close session ?
        # self._session.close()
        # self._session = None

    async def _start_download(self) -> None:
        """Fetch object metadata for read mode."""
        head = await self._s3_client.head_object(
            Bucket=self.bucket,
            Key=self.path,
        )
        self.size = head['ContentLength']
        self._file_size = self.size
        self._etag = head['ETag']
        self._position = 0
        self._eof = False
        LOG.debug("Opened S3 object %s/%s for reading (size: %d)", self.bucket, self.path, self.size)

    async def _start_upload(self) -> None:
        """Start multipart upload for write mode."""

        if "e" in self.flags:
            # O_EXCL: Check first if it exists. Note: there is a tiny data race here
            # If 2 transactions concurrently check and then create
            try:
                head = await self._s3_client.head_object(
                    Bucket=self.bucket,
                    Key=self.path,
                )
                raise FileExistsError(os.path.join(self.bucket, self.path))
            except self._s3_client.exceptions.NoSuchKey:
                pass

        response = await self._s3_client.create_multipart_upload(
            Bucket=self.bucket,
            Key=self.path,
        )
        self._multipart_upload_id = response["UploadId"]
        self._parts = []
        self._position = 0
        LOG.debug("Started multipart upload for %s/%s (ID: %s)", self.bucket, self.path, self._multipart_upload_id)

    async def _stop_download(self) -> None:
        """No-op for download cleanup."""
        pass

    async def _stop_upload(self) -> None:
        """Finalize or abort multipart upload."""
        if self._multipart_upload_id:
            if self._parts:
                try:
                    await self._s3_client.complete_multipart_upload(
                        Bucket=self.bucket,
                        Key=self.path,
                        UploadId=self._multipart_upload_id,
                        MultipartUpload={"Parts": self._parts},
                    )
                    LOG.debug("Completed multipart upload for %s/%s", self.bucket, self.path)
                except Exception as e:
                    LOG.error("Failed to complete multipart upload: %s", str(e))
                    await self._s3_client.abort_multipart_upload(
                        Bucket=self.bucket,
                        Key=self.path,
                        UploadId=self._multipart_upload_id,
                    )
            else:
                await self._s3_client.abort_multipart_upload(
                    Bucket=self.bucket,
                    Key=self.path,
                    UploadId=self._multipart_upload_id,
                )

    async def readinto(self, buffer: bytearray | memoryview) -> int:
        """
        Read data from S3 into buffer.
        Only valid in read mode ("r").
        Returns the number of bytes read.
        """
        if self.flags != "r":
            raise ValueError("readinto() only valid in read mode")
        if self._eof:
            return 0

        bytes_to_read = len(buffer)
        remaining = self._file_size - self._position
        if remaining <= 0:
            self._eof = True
            return 0

        bytes_to_read = min(bytes_to_read, remaining)
        if bytes_to_read <= 0:
            return 0

        response = await self._s3_client.get_object(
            Bucket=self.bucket,
            Key=self.path,
            Range=f"bytes={self._position}-{self._position + bytes_to_read - 1}",
        )

        data = bytearray()
        async for chunk in response["Body"]:
            data.extend(chunk)
            if len(data) >= bytes_to_read:
                break

        actual_bytes_read = len(data)
        buffer[:actual_bytes_read] = data
        self._position += actual_bytes_read
        self.bytes_read += actual_bytes_read

        if actual_bytes_read < bytes_to_read:
            self._eof = True

        return actual_bytes_read

    async def write(self, data: bytes | bytearray | memoryview) -> int:
        """
        Write data to S3.
        Only valid in write mode ("w").
        Returns the number of bytes written.
        """
        if self.flags != "w":
            raise ValueError("write() only valid in write mode")
        if self._multipart_upload_id is None:
            raise RuntimeError("Multipart upload not started")

        data_bytes = bytes(data) if not isinstance(data, bytes) else data
        bytes_to_write = len(data_bytes)

        part_number = len(self._parts) + 1
        response = await self._s3_client.upload_part(
            Bucket=self.bucket,
            Key=self.path,
            UploadId=self._multipart_upload_id,
            PartNumber=part_number,
            Body=data_bytes,
        )

        self._parts.append({
            "PartNumber": part_number,
            "ETag": response["ETag"],
        })
        self._position += bytes_to_write
        self.bytes_written += bytes_to_write

        return bytes_to_write

    def tell(self) -> int:
        """Current position in the file."""
        return self._position

    async def unlink(self, path: str) -> None:
        """Delete object."""
        async with self._session.client("s3",
                                        endpoint_url=self.endpoint,
                                        config=self.config,
                                        ) as s3_client:
            _ = await s3_client.delete_object(
                Bucket=self.bucket,
                Key=path.lstrip('/'),
            )

    async def make_read_only(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    import sys
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <conf> <src> <dst>")
        sys.exit(1)

    logging.basicConfig(level=logging.DEBUG,
                        format='%(name)s | %(message)s')

    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("aioboto3").setLevel(logging.WARNING)
    logging.getLogger("aiobotocore").setLevel(logging.WARNING)

    from . import ProgressBar
    from .posix import PosixFile

    async def main(src, dst):

        rctx = PosixFile()
        wctx = S3Stream(endpoint = 'http://localhost:9000',
                        bucket = 'lega',
                        access_key='lega',
                        secret_key='zzEH5pUK0gkrec1g9axPgZsKLGVXutVrarCoKm7t',
                      )
        
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
