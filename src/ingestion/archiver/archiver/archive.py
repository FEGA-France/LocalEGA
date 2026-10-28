# -*- coding: utf-8 -*-

import logging
import os
import hashlib
import time
from pathlib import Path
from hmac import compare_digest
import asyncio

from .utils import format_time, ChecksumsNotMatching, FilesizeNotMatching
from . import connectors

if os.getenv('LEGA_TRACING', None) == '1':
    from .connectors import ProgressBar as Tracer
else:
    from .connectors import NoTracer as Tracer

LOG = logging.getLogger(__name__)

async def _do_check(f, size, orgmd):
    LOG.debug('Comparing file sizes: %s', f.path)
    if size != f.size:
        raise FilesizeNotMatching(f.path, f.size, size)
    LOG.debug('Checksuming %s', f.path)
    tracer = Tracer('Checksuming', size)
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
    if not compare_digest(md.digest(), orgmd):
        computed = md.hexdigest()
        compared = orgmd.hex()
        LOG.error('Different file checksums')
        LOG.error('\t* computed: %s', computed)
        LOG.error('\t* compared: %s', compared)
        raise ChecksumsNotMatching(f.path, computed, compared)

async def _do_copy(r, v, b):

    tracer = Tracer('Archiving', r.size)
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
    speed = (bytes_read / elapsed_time) / (1<<20) # (1024 * 1024)
    LOG.info('Archival completed | elapsed time: %s | Speed: %s MB/s', format_time(elapsed_time), '{:.2f}'.format(speed))
    LOG.debug('Bytes read: %s [payload offset: %s]', bytes_read, r.tell())
    LOG.debug('Payload checksum: %s', payload_sha256.hexdigest())
    return payload_sha256.digest()


async def execute(data, rctx, vctx, bctx):

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
    
    internal = data['internal']
    ref_payload_filesize = internal['payload_size']
    ref_payload_checksum = bytes.fromhex(internal['payload_sha256'])

    contexts = [x for x in [vctx, bctx] if x]
    
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
        bfile = bctx.open(relative_path, 'ew', mkdirs=True) if bctx else connectors.noop()

        async with rfile as r, vfile as v, bfile as b:
            payload_sha256_checksum = await _do_copy(r,v,b)
            # Compare file size
            if ref_payload_filesize != r.tell():
                raise FilesizeNotMatching(filepath, r.tell(), ref_payload_filesize)
            # Compare with reference payload checksum
            if not compare_digest(payload_sha256_checksum, ref_payload_checksum):
                raise ChecksumsNotMatching(filepath, payload_sha256_checksum.hex(), ref_payload_checksum.hex())

        # We now read the files again
        for ctx in contexts:
            async with ctx.open(relative_path, 'r') as f:
                await _do_check(f, ref_payload_filesize, ref_payload_checksum)
                # Mark read-only
                await f.make_read_only()

        # Success: send completion
        data['internal']['relative_path'] = relative_path
        return data

    except FileExistsError as e:
        LOG.error('%r', e)
        raise
    except Exception as e:
        # LOG.error('Cleaning on: %r', e)
        # # Note: other concurrent messages do not reach that point
        # for ctx in contexts:
        #     try:
        #         await ctx.unlink(relative_path)
        #     except OSError as ee: 
        #         LOG.error('Removing %s | %s: %r', ctx, relative_path, ee)
        #         #pass
        raise


