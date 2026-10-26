import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat

import paramiko

from . import FileBase

LOG = logging.getLogger(__name__)

SND_BUFFER_SIZE = 1024 * 1024 # 1MB socket size and the kernel will double that
RCV_BUFFER_SIZE = SND_BUFFER_SIZE



class SFTPFile(FileBase):
    """SFTP file, read/write through the handle, from an ssh connection.

    One connection per file
    """
    
    CHUNK_SIZE = 32768 # max SFTP packets

    def __init__(self,
                 host,
                 username,
                 port = 22,
                 password = None,
                 private_key = None,
                 passphrase = None,
                 pool: ThreadPoolExecutor = None,
                 loop: asyncio.AbstractEventLoop = None) -> None:

        self.loop = loop or asyncio.get_running_loop()
        self.pool = pool or ThreadPoolExecutor(max_workers=2,
                                               thread_name_prefix="async_sftp")

        self.handle = None
        self.path = None
        self.offset = 0
        self.bytes_read = 0
        self.bytes_written = 0

        self.host = host
        self.port = int(port) or 22
        self.username = username
        self.password = password
        self.private_key = private_key
        self.passphrase = passphrase
        
        self.pkey = None
        self.shared_with = None
        LOG.debug('Created SFTPFile %s', id(self))

    @classmethod
    def build_from(cls, other,
                   host,
                   username,
                   port = 22,
                   password = None,
                   private_key = None,
                   passphrase = None):
        c = cls(host,
                username,
                port = port,
                password = password,
                private_key = private_key,
                passphrase = passphrase,
                pool = other.pool,
                loop = other.loop)
        c.shared_with = other
        LOG.debug('Created SFTPFile %s from %s', id(c), id(other))
        return c


    def __enter__(self):
        try:
            if self.passphrase:
                self.pkey = paramiko.Ed25519Key.from_private_key_file(self.private_key, self.passphrase)
        except Exception as e:
            LOG.error('Error with the passphrase: %r', e)
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        errors = []
        try:
            if self.sftp:
                s, self.sftp = self.sftp, None
                s.close()
        except Exception as e:
            errors.append(e)
        try:
            if self.ssh:
                s, self.ssh = self.ssh, None
                s.close()
        except Exception as e:
            errors.append(e)

        try:
            if self.pool and self.shared_with is None:
                LOG.error('Tearing down ThreadPool: %r', self.pool)
                pool, self.pool = self.pool, None
                pool.shutdown(wait=False)
        except Exception as e:
            errors.append(e)


        if errors and exc_type is None:
            raise errors[0] # first one
        return False


    @asynccontextmanager
    async def open(self,
                   path,
                   flags: str, # example 'r+', 'w', 'a'
                   ) -> None:

        try:
            self.connect()

            self.path = path

            # Make directories
            p = Path(path)
            d = ''
            for part in p.parts[:-1]: # not the filename
                if part == '/':
                    continue
                d += '/' + part
                LOG.info('Making remote dir: %s', d)
                try:
                    self.sftp.mkdir(d, mode=0o700)
                except OSError as e:
                    try:
                        s = self.sftp.stat(d)
                        if stat.S_ISDIR(s.st_mode):
                            continue
                        LOG.error('Dir error: %s', e)
                        raise ValueError('Not a directory')
                    except Exception as e2:
                        LOG.error('Dir stat error: %s', e2)
                        raise e


            LOG.info('Uploading file %s | flags: %s', path, flags)
            self.handle = self.sftp.open(path, mode=flags) #, bufsize=)
            # self.handle.setblocking(False)
            self.handle.set_pipelined(True) # don't wait for message confirmation. Capture errors in .close()

        except Exception as e:
            LOG.error('Error opening %s: %r', path, e)
            self._close_handle(ignore_exc=False)
            raise

        try:
            assert self.handle, "Missing SFTP file handle"
            yield self
        except Exception as e:
            LOG.error('Error on %s: %r', path, e)
            raise e
        finally: # Closing
            self._close_handle(ignore_exc=True, flush=True)


    def _close_handle(self, ignore_exc=True, flush=False) -> None:
        try:
            if self.handle:
                handle, self.handle = self.handle, None
                if flush:
                    handle.flush()
                handle.close()
        except Exception as e:
            if not ignore_exc:
                LOG.error('Error closing handle: %r', e)
                raise


    async def readinto(self, buffer: bytearray | memoryview, offset: int) -> int:
        if not self.handle:
            raise RuntimeError("Not open — use as a context manager")

        # ignoring offset
        n = await self.loop.run_in_executor(self.pool, self.handle.readinto, buffer)

        self.offset += n
        self.bytes_read += n
        return n

    async def write(self, data: bytes | bytearray | memoryview) -> int:
        if not self.handle:
            raise RuntimeError("Not open — use as a context manager")

        n = len(data)
        await self.loop.run_in_executor(self.pool, self.handle.write, data)
        # paramiko doesn't tell if fewer bytes were written
        # sftp tries to write them all

        self.offset += n
        self.bytes_written += n
        return n

    def connect(self):

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SND_BUFFER_SIZE)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCV_BUFFER_SIZE)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)  # Idle time before probes
        # sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # Interval between probes

        addr = (self.host, self.port)
        sock.connect(addr)

        class NoRekeyPaketizer(paramiko.transport.Packetizer):
            REKEY_PACKETS = pow(2, 37) # old value: pow(2, 29)
            REKEY_BYTES = pow(2, 37) # ~128 GB, old value: pow(2, 29)
            def need_rekey(self):
                """Override to always return False (disable client-initiated rekeying)."""
                return False
            def read_all(self, n, check_rekey=False):
                return super().read_all(n, check_rekey=False) # force false

        def transport_factory(s, disabled_algorithms=None):
            # disabled_algorithms = {
            #    'mac': ['hmac-sha1', 'hmac-md5'],  # Disable weak/old MACs
            #    'kex': ['diffie-hellman-group1-sha1'],
            #    'encryption': ['aes128-cbc', '3des-cbc'],  # Prefer AES-GCM
            # }
            disabled_algorithms = {
                'ciphers': [
                    '3des-cbc', 'aes128-cbc', 'aes192-cbc','aes256-cbc',
                    'aes128-ctr', 'aes192-ctr',
                    'aes128-gcm@openssh.com', 
                    #'aes256-ctr', 'aes256-gcm@openssh.com',
                    
                    # Disable all other ciphers to force ChaCha20
                    # Note: paramiko doesn't seem to support chacha20:
                    # https://github.com/paramiko/paramiko/blob/main/paramiko/transport.py#L176
                ],
                # Optionally, disable weak MACs and KEX to harden the connection
                'macs': ['hmac-sha1', 'hmac-md5', 'hmac-sha1-96', 'hmac-md5-96'],
                'keys': ['diffie-hellman-group1-sha1', 'diffie-hellman-group14-sha1'],
            }
            return paramiko.transport.Transport(s,
                                                # default_window_size=2097152,
                                                default_window_size=8 * 1024 * 1024,  # 8MB
                                                # default_max_packet_size=32768,
                                                default_max_packet_size=65536, # 64KB
                                                disabled_algorithms=disabled_algorithms,
                                                server_sig_algs=True,
                                                strict_kex=False,
                                                packetizer_class=NoRekeyPaketizer)

        ssh = paramiko.SSHClient()

        ssh.load_system_host_keys()
        # ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        
        LOG.info('SFTP connection %s [user: %s]', self.host, self.username)
        ssh.connect(self.host, port=self.port,
                    sock=sock, transport_factory=transport_factory,
                    username=self.username, password=self.password, pkey=self.pkey,
                    allow_agent=False, look_for_keys=False, compress=False)
        # raises Exception on errors: 
        # https://docs.paramiko.org/en/stable/api/client.html#paramiko.client.SSHClient
        self.ssh = ssh
        self.sftp = self.ssh.open_sftp()

        # Reset after connection
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SND_BUFFER_SIZE)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RCV_BUFFER_SIZE)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        

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

    logging.getLogger("paramiko").setLevel(logging.WARNING)

    from . import ProgressBar
    from .posix import PosixFile

    async def main(src, dst):

        rctx = PosixFile()
        wctx = SFTPFile(host='134.158.249.219',
                        port=22,
                        username='daz',
                        private_key='/Users/daz/.ssh/daz-fega',
                        passphrase='hello',
                        loop = rctx.loop)
        
        with rctx, wctx:
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
