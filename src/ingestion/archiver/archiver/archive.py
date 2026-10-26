# -*- coding: utf-8 -*-

import logging
import os
import hashlib
import time
from pathlib import Path
from hmac import compare_digest
import asyncio

from .utils import (format_time, set_info, remove_info, ChecksumsNotMatching)
from . import connectors

if os.getenv('LEGA_TRACING', None) == '1':
    from .connectors import ProgressBar as Tracer
else:
    from .connectors import NoTracer as Tracer

LOG = logging.getLogger(__name__)

async def _do_check(f, ctx, path, orgmd):
    LOG.debug('Checksuming [%s]: %s', ctx, path)
    tracer = Tracer('Checksuming', f.size)
    md = hashlib.sha256()
    chunk = bytearray(f.CHUNK_SIZE) # Reusable buffer
    start_time = time.time()
    while True:
        n = await f.readinto(chunk)
        if n == 0:
            break
        md.update(chunk[:n])
        tracer.update(n)
    tracer.close()
    elapsed_time = time.time() - start_time
    LOG.debug('Elpased time: %s', format_time(elapsed_time))
    c = md.hexdigest()
    if not compare_digest(cs, orgmd):
        LOG.error('Different file checksums')
        LOG.error('* computed: %s', c)
        LOG.error('* compared: %s', orgmd)
        raise ChecksumsNotMatching(path, c, orgmd)

async def _do_copy(r, v, b):

    assert destinations, "Missing archiving destinations"
    LOG.info('Archiving...') 

    tracer = Tracer('Processing', r.size)
    payload_sha256 = hashlib.sha256()
    start_time = time.time()

    bufsize = min(r.CHUNK_SIZE, v.CHUNK_SIZE)
    if b:
        bufsize = min(bufsize, b.CHUNK_SIZE)
    LOG.debug('Buffer size: %s', bufsize)

    chunk = bytearray(bufsize)
    bytes_read = 0

    while True:

        n = await r.readinto(chunk)
        if n == 0: # We were at the last segment
            break  # Exit the loop

        bytes_read += n

        data = chunk[:n]

        await v.write(data)
        payload_sha256.update(data)
        if b:
            await b.write(data)
        tracer.update(n)

    tracer.close()
    # del tracer
    elapsed_time = time.time() - start_time
    LOG.debug('Bytes read: %s [payload size: %s]', bytes_read, r.size)
    speed = (bytes_read / elapsed_time) / (1<<20) # (1024 * 1024)

    LOG.info('Archival completed | elapsed time: %s | Speed: %s MB/s', format_time(elapsed_time), '{:.2f}'.format(speed))

    # Checksum the output again
    payload_sha256_checksum = payload_sha256.hexdigest()
    LOG.debug('Payload checksum: %s', payload_sha256_checksum)
    return payload_sha256_checksum


async def execute(config, message):
    data = message.parsed
    filepath = data['filepath']
    accession_id = data['accession_id']

    # Split the accession_id by block of 3 letters
    # assert '..' not in accession_id, "No '..' in accession ID"
    accession_id = accession_id.replace('.', '_')
    relative_path = os.path.join(*list(accession_id[i:i+3]
                                       for i in range(0, len(accession_id), 3)))

    # prepend username to filepath
    username = data['user'].strip()
    assert '/' not in username
    filepath = os.path.join(username, filepath.lstrip('/'))
    
    # Load the source/vault/backup contexts
    rctx = connectors.load(config.select_section('source'))
    vctx = connectors.load(config.select_section('destination'),
                           shared_with=rctx) # share the ring

    do_backup = not config.getboolean('DEFAULT', 'skip_backup', fallback=False)
    if do_backup:
        bctx = connectors.load(config.select_section('backup'),
                               shared_with=vctx) # share the ring
        contexts = [vctx, bctx]
    else:
        contexts = [vctx]
    
    # In case we handle/receive twice the same message, (or archive
    # the same accession_id for 2 different staging files) we raise an
    # error for the second one. There is a tiny data race on file
    # open, they might both get a file descriptor, that's why we open
    # the destination file with O_EXCL
    #
    # ... and cue music
    try:

        rfile = rctx.open(filepath, 'r')
        vfile = vctx.open(relative_path, 'ew', mkdirs=True)

        async with rfile as r, vfile as v:
            payload_filesize = r.size
            if do_backup:
                async with bctx.open(relative_path, 'ew', mkdirs=True) as b:
                    payload_sha256_checksum = await _do_copy(r,v,b)
            else:
                payload_sha256_checksum = await _do_copy(r,v,None)

        # We now read the files again
        for ctx in contexts:
            async with ctx.open(relative_path, 'r') as f:
                if payload_filesize != f.size:
                    raise ValueError('non-matching filesizes')
                await _do_check(f, ctx, relative_path, payload_sha256_checksum)
                # read-only (umask already applied)
                await f.chmod((await f.mode()) & 0o444)

        # Success: send completion
        data['type'] = 'archival.completed'
        data['internal']['relative_path'] = relative_path
        await config.mq.publish(data, 'archival.completed',
                                correlation_id=message.correlation_id)

    except Exception as e:
        LOG.error('Cleaning on: %r', e)
        # Note: other concurrent messages do not reach that point
        for ctx in contexts:
            try:
                ctx.unlink(relative_path)
            except OSError: 
                LOG.error('Removing %s: %r', f, e)
                #pass
        raise

