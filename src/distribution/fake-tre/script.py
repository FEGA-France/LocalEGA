#!/usr/bin/env python

import sqlite3
import sys
from pathlib import Path
import os
import io
from functools import partial
from getpass import getpass

from crypt4gh import keys, header, lib

BOX_SQLITE = os.getenv('BOX_SQLITE', '/etc/ega/box.sqlite')
BOX_SECKEY = os.getenv('BOX_SECKEY', '/etc/ega/seckey')

def listing(cur):
    query ='''WITH cte AS (
                  SELECT inode,parent_inode,name,'' AS filepath, is_dir
                  FROM entries WHERE parent_inode = 1 and inode > 1
                UNION
                  SELECT e.inode, e.parent_inode, e.name,
                         t.filepath || '/' || e.name AS filepath,
                         e.is_dir
                  FROM entries e
                  JOIN cte t ON e.parent_inode = t.inode
              )
              SELECT filepath
              FROM cte
              WHERE not is_dir;'''
    res = cur.execute(query)
    for r in res.fetchall():
        print(r[0])

def get_info(cur, filepath):
    query ='''WITH cte AS (
                  SELECT inode,parent_inode,name,'' AS filepath, is_dir
                  FROM entries WHERE parent_inode = 1 and inode > 1
                UNION
                  SELECT e.inode, e.parent_inode, e.name,
                         t.filepath || '/' || e.name AS filepath,
                         e.is_dir
                  FROM entries e
                  JOIN cte t ON e.parent_inode = t.inode
              )
              SELECT f.header AS header,
                     concat(rtrim(f.mountpoint,'/'), '/', ltrim(f.rel_path,'/')) AS path
              FROM cte t
              JOIN files f ON t.inode = f.inode
              WHERE filepath = ?;'''

    res = cur.execute(query, (filepath,) )
    r = res.fetchone()

    if not r:
        raise FileNotFoundError()
    return (r[0], r[1])

def output(h, payload_path):
    with open(payload_path, 'rb') as f:
        sys.stdout.buffer.write(h)
        buf = bytearray(4096)
        while True:
            n = f.readinto(buf)
            if n == 0:
                break
            sys.stdout.buffer.write(buf[:n])

def decrypt_output(h, payload_path):

    passphrase = os.getenv('C4GH_PASSPHRASE')
    if passphrase:
        cb = lambda : passphrase
    else:
        cb = partial(getpass, prompt=f'Passphrase for {BOX_SECKEY}: ')

    # Unlock the private key
    # print("Decrypting seckey", BOX_SECKEY, file=sys.stderr)
    sk = keys.get_private_key(BOX_SECKEY, cb)

    # Decrypt the file (v1 style)
    # print("Decrypting header", file=sys.stderr)
    session_keys, edit_list = header.deconstruct(io.BytesIO(h), [(0, sk, None)])

    # print("Decrypting payload | ", len(session_keys), 'session-key found', file=sys.stderr)
    with open(payload_path, 'rb') as f:
        out = lib.limited_output(process=sys.stdout.buffer.write)
        next(out) # start it
        lib.body_decrypt(f, session_keys, out, 0)

    # version, data_encryptions, edits, _, uri = header.deconstruct(io.BytesIO(h), sk)

    # with open(payload_path, 'rb') as f:
    #     payload.decrypt(f, sys.stdout.buffer,
    #                     data_encryptions, edits, uri,
    #                     version=version)


if __name__ == '__main__':

    conn = sqlite3.connect(BOX_SQLITE)
    cur = conn.cursor()

    if len(sys.argv) < 2:
        listing(cur)
    else:
        filepath = sys.argv[1]

        decrypt = True
        if filepath.endswith('.c4gh'):
            filepath = filepath[:-5]
            decrypt = False

        h, payload_path = get_info(cur, filepath)
        if decrypt:
            decrypt_output(h, payload_path)
        else:
            output(h, payload_path)
