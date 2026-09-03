import logging
import os
import sys
import warnings
import argparse
from pathlib import Path
from logging.config import fileConfig, dictConfig
import json
import asyncio
import sqlite3

import asyncpg

LOG = logging.getLogger('genbox')

_here = Path(__file__).parent

db_dsn = os.getenv('DSN')

DEFAULT_SCHEMA = _here / 'schema.sql'
DEFAULT_LOGGER = _here / 'logger.json'

def decrypted_size(n):
    q, r = divmod(n, 65564)
    if r:
        q = q +1
    return n - q * 28

async def generate(args, cur, dsn):
    entries = 0
    files = 0
    LOG.info("Connecting to Vault DB")
    conn_src = await asyncpg.connect(dsn)
    try:
        LOG.info("Fetching Vault DB entries for %s", args.username)

        pubkeys = []
        for pubkey in args.pubkeys:
            with open(pubkey) as f:
                pubkeys.append(f.read().strip())

        # =========================
        # Datasets and Files
        # =========================
        rows = await conn_src.fetch('''SELECT *
                                       FROM sqlite_fs.datasets($1::text, $2::text[],
                                                              _include_user_keys => FALSE)''',
                                    args.username, pubkeys)

        cur.execute('''INSERT INTO entries(inode,name,parent_inode,nlink,is_dir)
                       VALUES (2,'datasets',1,2,1)''')

        for row in rows:
            res = cur.execute('''INSERT INTO entries(name,parent_inode,ctime,mtime,nlink,is_dir)
                                 VALUES (?,2,?,?,2,1)
                                 ON CONFLICT DO UPDATE SET ctime = excluded.ctime
                                 RETURNING inode''', (row['dataset_stable_id'],
                                                      row['dataset_ctime'],
                                                      row['dataset_mtime']))
            parent_ino = res.fetchone()[0]
            res = cur.execute('''INSERT INTO entries(name,parent_inode,ctime,mtime,nlink,size,is_dir)
                                 VALUES (?,?,?,?,1,?,0)
                                 RETURNING inode''', (row['filename'], parent_ino,
                                                      row['ctime'],
                                                      row['mtime'],
                                                      decrypted_size(row['payload_size'])))
            inode = res.fetchone()[0]
            res = cur.execute('''INSERT INTO files(inode,mountpoint,rel_path,header,payload_size)
                                 VALUES (?,?,?,?,?)''', (inode, args.vault_mountpoint,
                                                       row['rel_path'],
                                                       row['header'],
                                                       row['payload_size']))
            res = cur.execute('''INSERT INTO extended_attributes(inode,name,value)
                                 VALUES (?,'accession_id',?)''', (inode,
                                                                  row['stable_id']))


        # =========================
        # Reference files / Tools
        # =========================
        if args.additional_data:
            data = json.load(args.additional_data)
            assert isinstance(data, dict), 'Additional data should be a JSON-formatted dictionnary'
            
            for filepath, d in data.items(): 
                assert isinstance(filepath, str) and filepath[:1] == '/' # graceful degradation
                bits = filepath.ltrim('/').split('/') # split path
                parent_ino = 1 # since we use absolute path
                for p in bits[:-1]: # directories
                    res = cur.execute('''INSERT INTO entries(name,parent_inode,nlink,is_dir)
                                         VALUES (?,?,2,1)
                                         ON CONFLICT DO NOTHING
                                         RETURNING inode''', (p, parent_ino))
                    parent_ino = res.fetchone()[0]
                # last parent_inode
                res = cur.execute('''INSERT INTO entries(name,parent_inode,nlink,size,is_dir)
                                     VALUES (?,?,1,?,0)
                                     RETURNING inode''', (bits[-1],
                                                          parent_ino,
                                                          d['filesize']))
                inode = res.fetchone()[0]
                res = cur.execute('''INSERT INTO files(inode,mountpoint,rel_path,payload_size)
                                     VALUES (?, '', ?,?)''', (inode, # yeah, hard-coding it
                                                              d['rel_path'],
                                                              d['filesize']))
                res = cur.execute('''INSERT INTO extended_attributes(inode,name,value)
                                     VALUES (?,'version',?)''', (inode,
                                                                 row['version']))


        if not args.silent:
            print(f"Successfully created", args.filename, file=sys.stderr)
            rows = cur.execute('SELECT parent_inode, inode, size, name FROM entries WHERE inode > 1;')
            print('{:>12} | {:<12} | {:>12} | {}'.format('Parent', 'Inode', 'Size', 'Name'), file=sys.stderr)
            print('{:->12}-|-{:->12}-|-{:->12}-|-{:-<20}'.format('-','-','-','-'), file=sys.stderr)
            for row in rows.fetchall():
                print('{:>12} | {:>12} | {:>12} | {}'.format(*row), file=sys.stderr)

    finally:
        if conn_src:
            LOG.debug("Closing Vault DB connection")
            await conn_src.close()

if __name__ == '__main__':

    parser = argparse.ArgumentParser(#prog='ProgramName',
                                     description='Generate the SQLite box for a given user',
                                     epilog='This requires the Vault DB connection as environment variable "DSN"')

    parser.add_argument('username')
    parser.add_argument('filename')
    parser.add_argument('-s', '--schema',
                        help="Run this SQL script first",
                        default=DEFAULT_SCHEMA)
    parser.add_argument('-l', '--log',
                        help="Logger for verbose/debug output",
                        default=DEFAULT_LOGGER) # use -q to "cancel" it
    parser.add_argument('-d', '--reset',
                        help="Delete <filename> before running",
                        action='store_true')
    parser.add_argument('-q', '--silent',
                        help="No verbose output",
                        action='store_true')
    parser.add_argument('--vault-mountpoint',
                        help="Set the vault mountpoint",
                        default='/data/vault')
    parser.add_argument('--additional-data',
                        help="JSON-formatted file of additional tools and reference files")
    parser.add_argument('-k','--pk', action='append',
                        dest='pubkeys', metavar='pubkey',
                        help='Recipient public key path. (Can be repeated)')

    args = parser.parse_args()

    if not args.silent and args.log:
        with open(args.log, 'rt') as stream: # let it fail if not found
            dictConfig(json.load(stream))
    else:
        warnings.warn("No logging supplied", UserWarning, stacklevel=2)

    if not db_dsn:
        LOG.error('Missing Vault DB connection as environment variable "DSN"')
        sys.exit(1)

    schema = None
    if args.schema:
        LOG.info("Reading schema from %s",args.schema)
        with open(args.schema, 'r') as f:
            schema = f.read()

    if args.reset:
        if not schema:
            raise ValueError('Missing schema while resetting the file')
        LOG.info("Deleting %s", args.filename)
        try:
            os.remove(args.filename)
        except FileNotFoundError as e:
            LOG.error('%s', e)

    # ...and cue music 
    try:
        LOG.info("Opening SQLite %s", args.filename)
        conn = sqlite3.connect(args.filename) # autocommit=True, isolation_level=None)
        assert conn, f"Can't connect to {args.filename}"
        if schema: # install the tables
            LOG.info("Loading schema")
            conn.executescript(schema)
            conn.commit()
        asyncio.run(generate(args, conn.cursor(), db_dsn))
        conn.commit()
    finally:
        conn.close()
