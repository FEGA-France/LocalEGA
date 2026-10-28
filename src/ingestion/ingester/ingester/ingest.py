# -*- coding: utf-8 -*-

import logging
import os
import hashlib
import time
from hmac import compare_digest
import io

import crypt4gh
from crypt4gh import lib as c4gh, sodium
from . import exceptions, connectors
from .utils import format_time

if os.getenv('LEGA_TRACING', None) == '1':
    from .connectors import ProgressBar as Tracer
else:
    from .connectors import NoTracer as Tracer

LOG = logging.getLogger(__name__)


async def parse_header(service_key, rctx, path):
    async with rctx.open(path, 'r') as infile:
        try:

            stream = io.BytesIO()
            buf = bytearray(16)
            if await infile.readinto(buf) != 16:
                raise ValueError('Header too small')
            stream.write(buf)
            # Packets count
            packets_count = int.from_bytes(bytes(buf[12:16]), byteorder='little')
            # LOG.debug('This header contains %d packets', packets_count)
            # Spit out one packet at a time
            for _ in range(packets_count):
                encrypted_packet_len = await infile.read(4)
                stream.write(encrypted_packet_len)
                encrypted_packet_data = await infile.read(int.from_bytes(encrypted_packet_len, byteorder='little') - 4)
                stream.write(encrypted_packet_data)

            stream.seek(0,io.SEEK_SET)
            # Get session keys
            session_keys, edit_list = crypt4gh.header.deconstruct(stream, [service_key])
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
        return session_keys, header_len

def decrypt(n, ciphertext, plaintext, output, session_keys, random_key=None):

    nsegments, remainder = divmod(n, c4gh.CIPHER_SEGMENT_SIZE)
    if remainder:
        nsegments += 1
        assert remainder > c4gh.CIPHER_DIFF

    # LOG.debug('Decrypting %s bytes => %s segments', n, nsegments)

    psize = 0
    for segment_id in range(nsegments):
        if segment_id < nsegments - 1:
            size = c4gh.CIPHER_SEGMENT_SIZE
        else:
            size = remainder or c4gh.CIPHER_SEGMENT_SIZE

        # LOG.debug('Decrypting segment %s | size: %s', segment_id, size)
                    
        # Get pointers at the correct offsets
        cstart = segment_id * c4gh.CIPHER_SEGMENT_SIZE
        pstart = segment_id * c4gh.SEGMENT_SIZE
                    
        c = ciphertext[cstart:cstart+size]
        p = plaintext[pstart:pstart+size - c4gh.CIPHER_DIFF]
        o = output[cstart:cstart+size]
                
        clen = len(c)
        try:
            plen = c4gh.decrypt_block(p, c, session_keys)
            assert plen == size - c4gh.CIPHER_DIFF, f"Invalid plaintext size | segment {segment_id}"
            if random_key:
                olen = sodium.chacha20poly1305_encrypt(o, p[:plen], random_key)
                assert olen == clen, "Invalid output size"
            psize += plen
        except Exception as v: # capture any error here
            LOG.error('Payload reencryption error: %r', v, exc_info=True)
            raise exceptions.Crypt4GHPayloadError() from v
                
    # LOG.debug('n: %s | adjusted n: %s | psize:%s',
    #           n, n - nsegments * c4gh.CIPHER_DIFF, psize)
    assert psize == n - nsegments * c4gh.CIPHER_DIFF, "invalid plaintext size"
    return psize


async def execute(data, path,
                  service_key, master_key, rctx, wctx,
                  do_reencryption = True,
                  bufsize = None,
                  inbox_checksum = None):

    bufsize = bufsize or c4gh.CIPHER_SEGMENT_SIZE # reset

    LOG.debug('Reading header from %s', path)
    session_keys, header_len = await parse_header(service_key, rctx, path)
    LOG.debug('Found %d session keys | header len: %s', len(session_keys), header_len)
    # LOG.debug('session key: %s', session_keys[0].hex())

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
          for x in crypt4gh.header.encrypt(p, [master_key])
         ])

    
    inbox_sha256 = hashlib.sha256()
    staging_sha256 = hashlib.sha256()
    plaintext_sha256 = hashlib.sha256()
    start_time = time.time()

    bytes_read = 0
    bytes_written = 0

    LOG.debug('Verifying payload')
    rfile = rctx.open(path, 'r')
    wfile = wctx.open(path, 'w', mkdirs=True) # not ew, we want to create+truncate

    async with rfile as r, wfile as w:

        tracer = Tracer('Processing', r.size)

        #
        # We try several segments at once, to avoid I/O.
        # We allocate large buffers that we share across encryption/decryption
        #
        # We checksum the plaintext and don't leave any trace on disk
        #
        q, rem = divmod(bufsize, c4gh.CIPHER_SEGMENT_SIZE)
        factor = max(1, q + (1 if rem else 0))
        LOG.debug('Buffering %d segments', factor)
        
        ciphertext_len = c4gh.CIPHER_SEGMENT_SIZE * factor
        plaintext_len = c4gh.SEGMENT_SIZE * factor
        
        ciphertext = bytearray(ciphertext_len)
        plaintext = bytearray(plaintext_len)
        output = bytearray(ciphertext_len)
        
        # Read the original header first, position the stream at the payload
        original_header = await r.read(header_len)
        inbox_sha256.update(original_header)

        #await w.write(master_header)
        #staging_sha256.update(master_header)

        while True:
                
            n = await r.readinto(ciphertext)
            if n == 0:
                break # We were at the last segment. Exits the loop

            bytes_read += n
            inbox_sha256.update(ciphertext[:n])

            # do the job
            psize = decrypt(n, ciphertext, plaintext, output, session_keys, random_key=random_key)
            plaintext_sha256.update(plaintext[:psize])

            # output data
            selection = output[:n] if do_reencryption else ciphertext[:n]
            await w.write(selection)
            bytes_written += n
            staging_sha256.update(selection)
            tracer.update(n)

        tracer.close()

    elapsed_time = time.time() - start_time
    LOG.debug('Elpased time: %s', format_time(elapsed_time))
    LOG.debug('Bytes read: %s [payload size: %s]', bytes_read, bytes_written)
    speed = (bytes_read / elapsed_time) / (1<<20) # (1024 * 1024)
    LOG.debug('Speed: %s MB/s', '{:.2f}'.format(speed))

    # Compare inbox checksum vs computed checksum
    computed_inbox_checksum = inbox_sha256.hexdigest()
    if inbox_checksum is not None:
        LOG.info('Comparing with inbox checksum: %s', inbox_checksum)
        if not compare_digest(bytes.fromhex(inbox_checksum), # hex -> bytes
                              inbox_sha256.digest()):
            raise exceptions.ChecksumsNotMatching(path, computed_inbox_checksum, inbox_checksum) # hex

    LOG.info('Verification completed')
    plaintext_checksum = plaintext_sha256.hexdigest()
    data['decrypted_checksums'] = [{'type': 'sha256', 'value': plaintext_checksum}]
    job_id = data['internal']['job_id'] # let it crash if missing
    data['internal'] = {
        'job_id': job_id,
        'payload_sha256': staging_sha256.hexdigest(),
        'payload_size': bytes_written,
        'header': master_header.hex(),
        'plaintext_sha256': plaintext_checksum,
        'original_sha256': computed_inbox_checksum,
        'sk_hashes': sk_hashes
    }
    return data
