"""
Async S3 file I/O using aioboto3.

This module provides an async S3 file connector that implements the FileBase interface.

Usage:
    wctx = S3File(endpoint='localhost:9000', access_key='...', secret_key='...')
    with wctx:
        async with wctx.open(bucket, key) as r:
            await r.readinto(buf)
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import aioboto3
from botocore.config import Config

from . import FileBase

LOG = logging.getLogger(__name__)

class S3File(FileBase):
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
        self.access_key = access_key
        self.secret_key = secret_key
        self.session_token = session_token
        self.config = Config(signature_version=signature_version or "s3v4")
        self.region = region or 'us-east-1'
        self.session_kwargs = session_kwargs
        self._session = None


    def __enter__(self) -> "S3File":
        self._session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            aws_session_token=self.session_token,
            region_name=self.region,
            **self.session_kwargs,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # self._session = None
        return False

    @asynccontextmanager
    async def open(
        self,
        path: str,
    ):
        """
        Async context manager for S3 operations.
        Configures, creates client, starts operation, and yields self.
        """
        # Configure for this operation
        self.key = path.lstrip('/')
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

        # Create client
        async with self._session.client("s3",
                                        endpoint_url=self.endpoint,
                                        config=self.config,
                                        ) as s3_client:
            self._s3_client = s3_client  # Store reference for use in methods

            # Start operation
            head = await self._s3_client.head_object(
                Bucket=self.bucket,
                Key=self.key,
            )
            self.size = head['ContentLength']
            self._file_size = self.size
            self._etag = head['ETag']
            self._position = 0
            self._eof = False
            LOG.debug("Opened S3 object %s/%s for reading (size: %d)", self.bucket, self.key, self.size)

            try:
                yield self
            finally:
                # Stop operation
                await self._stop_download()

            # remove referernce
            self._s3_client = None

    async def readinto(self, buffer: bytearray | memoryview) -> int:
        """
        Read data from S3 into buffer.
        Only valid in read mode ("r").
        Returns the number of bytes read.
        """
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
            Key=self.key,
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
