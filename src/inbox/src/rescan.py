#!/usr/bin/env python3

import sys
import os
import asyncio
import json
import uuid
import hashlib
from resource import getpagesize
import pwd

import aiormq

INBOX =  os.getenv('LEGA_INBOX')
assert INBOX, "Missing LEGA_INBOX environment"

BUFSIZE = os.getenv('BUFFER_SIZE', getpagesize())

def scandir(directory):
    for entry in os.scandir(directory):
        if entry.is_dir(follow_symlinks=False):
            if entry.name[0] != '.': # skip hidden dirs
                yield from scandir(entry.path)
        else:
            if entry.name[0] != '.': # skip hidden files
                yield entry


async def main(username):

    assert '/' not in username, "Invalid username"
    # Can't check if username exists within FEGA/LEGA: no NSS!

    directory = os.path.abspath(os.path.join(INBOX, username))
    assert os.path.isdir(directory), "Not a directory"

    # We connect to the local broker
    connection = await aiormq.connect('amqp://guest:guest@localhost:5672/%2F')
    channel = await connection.channel(publisher_confirms=True)

    # Prepare the publish function
    properties = aiormq.spec.Basic.Properties(delivery_mode=2,
                                              content_type='application/json')

    async def publish(body, correlation_id=None):
        m = json.dumps(body, indent=4).encode()
        if correlation_id:
            properties.correlation_id = correlation_id
        return await channel.basic_publish(m,
                                           exchange='amq.topic',
                                           routing_key='files.inbox',
                                           properties=properties)

    _username = pwd.getpwuid(os.getuid()).pw_name

    # First send a reset
    print('-'*10,'Erasing all inbox entries from', username, file=sys.stderr)
    await publish({ 'operation': 'remove',
                    'user': _username,
                    'filepath': f'/upload/{username}/' })
    
    print('-'*10,'Scanning', directory, file=sys.stderr)

    dlen = len(directory)
    for entry in scandir(directory): # already in "directory"
        md = hashlib.sha256()
        with open(entry.path, 'rb') as f:
            b = bytearray(BUFSIZE)
            while True:
                n = f.readinto(b)
                if n == 0:
                    break
                md.update(b[:n])
        # send
        filepath = entry.path[dlen:]
        sha256 = md.hexdigest()
        s = entry.stat() # might be a syscall
        correlation_id = str(uuid.uuid4())
        print(sha256, correlation_id, filepath)
        message = {
            'operation': 'upload',
            'user': _username,
            'filepath': f'/upload/{username}' + filepath,
            'encrypted_checksums': [ {'type': 'sha256', 'value': sha256}],
            'filesize': s.st_size,
            'file_last_modified': int(s.st_mtime), # in seconds
        }
        await publish(message, correlation_id=correlation_id)
        

    print('-'*10, 'Scan terminated', file=sys.stderr)

    await channel.close()
    await connection.close()


if __name__ == '__main__':

    if len(sys.argv) < 2:
        print(f'Usage: {os.path.basename(sys.argv[0])} <username>')
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
