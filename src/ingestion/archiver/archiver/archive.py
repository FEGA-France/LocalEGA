# -*- coding: utf-8 -*-

import logging
import os
import hashlib
import time
from pathlib import Path
from hmac import compare_digest
import asyncio

from .utils import (format_time, set_info, remove_info, ChecksumsNotMatching)
from .transfer import AsyncTransfer

if os.getenv('LEGA_TRACING', None) == '1':
    from .transfer import ProgressBar as Tracer
else:
    from .transfer import NoTracer as Tracer

LOG = logging.getLogger(__name__)

_QUERY = None

async def checkum_and_compare(path, filesize, orgmd, chunksize=1<<23): # 8 MB
    LOG.debug('Reading again file %s', path)
    if filesize != os.stat(path).st_size:
        raise ValueError("Filesizes don't match")
    tracer = Tracer('Checksuming', filesize)
    md = hashlib.sha256()
    chunk = bytearray(chunksize) # Reusable buffer
    start_time = time.time()
    async with AsyncTransfer(path, None) as t:
        while True:
            n = await t.readinto(chunk)
            if n == 0:
                break
            md.update(chunk[:n])
            tracer.update(n)
    tracer.close()
    elapsed_time = time.time() - start_time
    LOG.debug('Elpased time: %s', format_time(elapsed_time))

    c = md.hexdigest()
    
    if not compare_digest(c, orgmd): # could use c != orgmd
        LOG.error('Different file checksums')
        LOG.error('* computed: %s', c)
        LOG.error('* compared: %s', orgmd)
        raise ChecksumsNotMatching(path, c, orgmd)


async def _do_copy(bufsize, staging_path, vault_path, backup_path):

    LOG.info('Copying...') 
    payload_filesize = os.stat(staging_path).st_size
    tracer = Tracer('Processing', payload_filesize)
    payload_sha256 = hashlib.sha256()
    start_time = time.time()

    # Create directories
    Path(vault_path).parent.mkdir(parents=True, exist_ok=True)
    Path(backup_path).parent.mkdir(parents=True, exist_ok=True)

    chunk = memoryview(bytearray(bufsize))
    bytes_read = 0

    async with AsyncTransfer(staging_path, [vault_path, backup_path]) as t:

        while True:

            n = await t.readinto(chunk)
            if n == 0: # We were at the last segment
                break  # Exit the loop

            bytes_read += n

            await t.write(chunk[:n])
            payload_sha256.update(chunk[:n])
            tracer.update(n)

    tracer.close()
    # del tracer
    elapsed_time = time.time() - start_time
    LOG.debug('Bytes read: %s [payload size: %s]', bytes_read, payload_filesize)
    speed = (bytes_read / elapsed_time) / (1<<20) # (1024 * 1024)

    LOG.info('Archival completed | elapsed time: %s | Speed: %s MB/s', format_time(elapsed_time), '{:.2f}'.format(speed))

    # Checksum the output again
    payload_sha256_checksum = payload_sha256.hexdigest()
    LOG.debug('Payload checksum: %s', payload_sha256_checksum)

    # We now read the Vault file again
    LOG.info('Checksuming %s', vault_path)
    await checkum_and_compare(vault_path,
                              payload_filesize, payload_sha256_checksum,
                              chunksize=bufsize)

    # Same for the backup file
    LOG.info('Checksuming %s', backup_path)
    await checkum_and_compare(backup_path,
                              payload_filesize, payload_sha256_checksum,
                              chunksize=bufsize)

    # saving info on success
    set_info(vault_path, 'sha256', payload_sha256_checksum)

    # Vault and Backup file: read-only (umask already applied)
    os.chmod(vault_path,
             os.stat(vault_path).st_mode & 0o444)
    os.chmod(backup_path, 
             os.stat(backup_path).st_mode & 0o444)


async def execute(config, message):
    data = message.parsed
    filepath = data['filepath']
    username = data['user']

    accession_id = data['accession_id']
        
    LOG.info('Processing %s: [%s]%s', accession_id, username, filepath)
        
    staging_prefix = config.get('staging', 'location', raw=True)
    staging_path = os.path.join(staging_prefix % username, filepath.lstrip('/'))
    LOG.debug('Staging path: %s', staging_path)

    if not os.path.isfile(staging_path):
        raise FileNotFoundError(f'Staging path: {filepath} | User: {username}')
    
    # Split the accession_id by block of 3 letters
    # assert '..' not in accession_id, "No '..' in accession ID"
    accession_id = accession_id.replace('.', '_')
    relative_path = os.path.join(*list(accession_id[i:i+3] for i in range(0, len(accession_id), 3)))

    vault_prefix = config.get('vault', 'location')
    vault_path = os.path.join(vault_prefix, relative_path)
    LOG.debug('Vault path: %s', vault_path)
    backup_prefix = config.get('backup', 'location')
    backup_path = os.path.join(backup_prefix, relative_path)
    LOG.debug('Backup path: %s', backup_path)
    
    # In case we handle/receive twice the same message, (or archive
    # the same accession_id for 2 different staging files) we raise an
    # error for the second one. There is a tiny data race on file
    # open, they might both get a file descriptor, that's why we open
    # the destination file with O_EXCL
    if os.path.isfile(vault_path):
        raise ValueError(f'Vault path already exists: {vault_path}')

    bufsize = config.getint('DEFAULT', 'bufsize', fallback=1<<23) # 8 MB
    LOG.debug('Buffer size: %s', bufsize)

    # ... and cue music
    try:
        await _do_copy(bufsize, staging_path, vault_path, backup_path)

        # Success: send completion
        data['type'] = 'archival.completed'
        data['internal']['relative_path'] = relative_path
        await config.mq.publish(data, 'archival.completed',
                                correlation_id=message.correlation_id)

    except Exception as e:
        LOG.error('Cleaning on: %r', e)
        # Note: other concurrent messages do not reach that point
        for f in [vault_path, backup_path]:
            try:
                remove_info(f, 'sha256')
                #remove_info(f, 'decrypted_sha256')
                os.unlink(f)
            except OSError: 
                LOG.error('Removing %s: %r', f, e)
                #pass
        raise

