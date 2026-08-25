# -*- coding: utf-8 -*-

import logging
import io
import os
import hashlib
import time
import asyncio
from pathlib import Path
from hmac import compare_digest
from itertools import chain

import crypt4gh
from crypt4gh import lib as c4gh, sodium
from .transfer import AsyncTransfer
from . import exceptions

if os.getenv('LEGA_TRACING', None) == '1':
    from .transfer import ProgressBar as Tracer
else:
    from .transfer import NoTracer as Tracer

LOG = logging.getLogger(__name__)


async def checkum_and_compare(path, orgmd, chunksize=1<<23): # 8 MB
    LOG.debug('Reading again file %s', path)
    filesize = os.stat(path).st_size
    tracer = Tracer('Checksuming', filesize)
    md = hashlib.sha256()
    chunk = bytearray(chunksize)  # Reusable buffer
    start_time = time.time()
    async with AsyncTransfer(path, '/dev/null') as t:
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
        raise exceptions.ChecksumsNotMatching(path, c, orgmd)


def parse_header(config, inbox_path):
    with open(inbox_path, 'rb') as infile:
        try:
            service_key = (0, config.service_key.private(), None) # not checking the sender
            # Get session keys
            session_keys, edit_list = crypt4gh.header.deconstruct(infile, [service_key])
            #LOG.debug('Session keys: %s', session_keys)
        except Exception as e:
            LOG.error('Decryption error: %r', e)
            raise exceptions.Crypt4GHHeaderDecryptionError() from e

        # Raise error we could not decrypt the header (ie no session keys retrieved)
        if not session_keys:
            raise exceptions.SessionKeyDecryptionError('No session keys found')

        if edit_list:
            raise exceptions.FromUser('Support for Crypt4GH edit list has been removed')
        
        header_len = infile.tell() # we're right after the header
        infile.seek(0,0)
        header_bytes = infile.read(header_len)
        return session_keys, header_bytes, header_len


def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f'{int(hours)}:{int(minutes):02}:{int(seconds):02}'
    elif minutes > 0:
        return f'{int(minutes):02}:{int(seconds):02}'
    else:
        return f'{int(seconds)} seconds'

async def _do_execute(config, data, correlation_id,
                      inbox_path, staging_path,
                      do_reencryption=True):

    LOG.debug('Reading header from %s', inbox_path)
    session_keys, inbox_header, header_len = parse_header(config, inbox_path)
    LOG.debug('Found %d session keys | header len: %s', len(session_keys), header_len)

    inbox_sha256 = hashlib.sha256()
    inbox_sha256.update(inbox_header)

    # LOG.debug('session key: %s', session_keys[0].hex())
    # LOG.debug('session key: %s', list(session_keys[0]))

    master_key = (0, config.service_key.private(), config.master_pubkey)
    # from ingestion to recipient master

    LOG.debug('Creating Crypt4GH packets | reencryption: %s', do_reencryption)
    if do_reencryption:
        random_key = os.urandom(32)
        # Creating a new header with a new (random) session key
        # we use only one session key for all blocks
        header_packets = [crypt4gh.header.make_packet_data_enc(0, random_key)]
        sk_hashes = [hashlib.sha256(random_key).hexdigest()]
    else:
        random_key = None
        header_packets = [crypt4gh.header.make_packet_data_enc(0, session_key)
                          for session_key in session_keys]
        sk_hashes = [ hashlib.sha256(sk).hexdigest()
                      for sk in session_keys]

    LOG.debug('Creating Crypt4GH header')
    master_header = crypt4gh.header.serialize(
        [ x
         for p in header_packets
         for x in crypt4gh.header.encrypt(p, [master_key])]
    )

    LOG.debug('Verifying payload')
    payload_filesize = os.stat(inbox_path).st_size - header_len

    nsegments, remainder = divmod(payload_filesize, c4gh.CIPHER_SEGMENT_SIZE)
    if remainder:
        nsegments += 1
        assert remainder > c4gh.CIPHER_DIFF
    LOG.debug('Handling %d segments', nsegments)

    tracer = Tracer('Processing', payload_filesize)
    staging_sha256 = hashlib.sha256()
    plaintext_sha256 = hashlib.sha256()
    start_time = time.time()

    async with AsyncTransfer(inbox_path, staging_path) as t:
        try:

            # Move passed the header
            # original_header = await t.read(header_len)
            t.src_offset = header_len
            #await t.write(master_header)
            #staging_sha256.update(master_header)

            #
            # We try several segments at once, to avoid I/O.
            # We allocate large buffers that we share across encryption/decryption
            #
            # We also allocate a large nonce at once.
            # Getting randombytes should not block:
            # https://doc.libsodium.org/doc/generating_random_data
            #
            # We checksum the plaintext and don't leave any trace on disk
            #
            bufsize = config.getint('DEFAULT', 'bufsize', fallback=c4gh.CIPHER_SEGMENT_SIZE)
            q, r = divmod(bufsize, c4gh.CIPHER_SEGMENT_SIZE)
            factor = max(1, q + (1 if r else 0))
            LOG.debug('Buffering %d segments', factor)

            ciphertext_len = c4gh.CIPHER_SEGMENT_SIZE * factor
            plaintext_len = c4gh.SEGMENT_SIZE * factor

            ciphertext = memoryview(bytearray(ciphertext_len))
            plaintext = memoryview(bytearray(plaintext_len))
            output = memoryview(bytearray(ciphertext_len))

            bytes_read = 0

            while True:

                n = await t.readinto(ciphertext)
                if n == 0:
                    break # We were at the last segment. Exits the loop

                bytes_read += n
                inbox_sha256.update(ciphertext[:n])

                nsegments, remainder = divmod(n, c4gh.CIPHER_SEGMENT_SIZE)
                if remainder:
                    nsegments += 1
                    assert remainder > c4gh.CIPHER_DIFF

                # Call it once for nsegments
                psize = 0

                for segment_id in range(nsegments):
                    if segment_id < nsegments - 1:
                        size = c4gh.CIPHER_SEGMENT_SIZE
                    else:
                        size = remainder or c4gh.CIPHER_SEGMENT_SIZE

                    #LOG.debug('Re-encrypting segment %s | size: %s', segment_id, size)

                    # Get pointers at the correct offsets
                    cstart = segment_id * c4gh.CIPHER_SEGMENT_SIZE
                    pstart = segment_id * c4gh.SEGMENT_SIZE

                    c = ciphertext[cstart:cstart+size]
                    p = plaintext[pstart:pstart+size - c4gh.CIPHER_DIFF]
                    o = output[cstart:cstart+size]

                    clen = len(c)
                    plen = c4gh.decrypt_block(p, c, session_keys)
                    assert plen == size - c4gh.CIPHER_DIFF, "Invalid plaintext size"
                    if do_reencryption:
                        olen = sodium.chacha20poly1305_encrypt(o, p[:plen], random_key)
                        assert olen == clen, "Invalid output size"
                    psize += plen

                # LOG.debug('n: %s | adjusted n: %s | psize:%s',
                #           n, n - nsegments * c4gh.CIPHER_DIFF, psize)
                assert psize == n - nsegments * c4gh.CIPHER_DIFF, "invalid plaintext size"
                plaintext_sha256.update(plaintext[:psize])

                if do_reencryption:
                    selection = output[:n]
                else:
                    selection = ciphertext[:n]

                await t.write(selection)
                staging_sha256.update(selection)
                tracer.update(n)

        except Exception as v: # capture any error here
            LOG.error('Payload reencryption error: %r', v, exc_info=True)
            raise exceptions.Crypt4GHPayloadError() from v
        finally:
            tracer.close()
            del tracer

    elapsed_time = time.time() - start_time
    LOG.debug('Elpased time: %s', format_time(elapsed_time))
    LOG.debug('Bytes read: %s [payload size: %s]', bytes_read, payload_filesize)
    speed = (bytes_read / elapsed_time) / (1<<20) # (1024 * 1024)
    LOG.debug('Speed: %s MB/s', '{:.2f}'.format(speed))

    LOG.info('Verification completed')

    # Checksum the output again
    staging_checksum = staging_sha256.hexdigest()
    staging_filesize = os.stat(staging_path).st_size

    LOG.debug('Checksum %s: %s', staging_path, staging_checksum)
    await checkum_and_compare(staging_path, staging_checksum)

    # Add decrypted checksums to message, to get an accession id
    plaintext_checksum = plaintext_sha256.hexdigest()

    data['decrypted_checksums'] = [{'type': 'sha256', 'value': plaintext_checksum}]

    job_id = data['internal']['job_id'] # let it crash if missing
    data['internal'] = {
        'job_id': job_id,
        'payload_sha256': staging_checksum,
        'payload_size': staging_filesize,
        'header': master_header.hex(),
        'plaintext_sha256': plaintext_checksum,
        'original_sha256': inbox_sha256.hexdigest(),
        'sk_hashes': sk_hashes
    }

    # Publish the verified message, to Central EGA
    data['type'] = 'ingestion.completed'
    await config.mq.publish(data, 'ingestion.completed', correlation_id=correlation_id)


async def execute(config, message): # 128 segments = 8 MB

    data = message.parsed
    filepath = data['filepath']
    username = data['user']

    LOG.info('Processing [%s]%s', username, filepath)

    inbox_prefix = config.get('inbox', 'location', raw=True)
    staging_prefix = config.get('staging', 'location', raw=True)
    
    inbox_path = os.path.join(inbox_prefix % username, filepath.strip('/') )
    LOG.debug('Inbox path %s', inbox_path)
    staging_path = os.path.join(staging_prefix % username, filepath.strip('/') )
    LOG.debug('Staging path: %s', staging_path)
    
    if not os.path.exists(inbox_path):
        raise exceptions.NotFoundInInbox(username, filepath)  # return early

    Path(staging_path).parent.mkdir(parents=True, exist_ok=True)

    do_reencryption = not config.getboolean('DEFAULT', 'skip_reencryption', fallback=False)

    try:
        await _do_execute(config, data, message.header.properties.correlation_id,
                          inbox_path, staging_path,
                          do_reencryption=do_reencryption)
    except Exception as e:
        LOG.error('Cleaning staging on: %r', e)
        try:
            os.unlink(staging_path)
        except OSError:
            pass
        raise


if __name__ == "__main__":

    k = memoryview(bytearray(32))
    n = memoryview(bytearray(12))
    p = memoryview(bytearray(c4gh.SEGMENT_SIZE))
    c = memoryview(bytearray(c4gh.CIPHER_SEGMENT_SIZE))
    o = memoryview(bytearray(c4gh.SEGMENT_SIZE))

    crypto.randombytes(k)
    crypto.randombytes(n)
    crypto.randombytes(p)

    crypto.encrypt(c, p, n, k) # p => c
    crypto.decrypt(o, c, k)    # c => o

    print('key:', k[:10].hex())
    print('nonce:', n[:10].hex())
    print('plaintext:', p[:10].hex())
    print('ciphertext:', c[12:22].hex())
    print('output:', o[:10].hex())

    if o == p:
        print('All good')
    else:
        print('Not working')
