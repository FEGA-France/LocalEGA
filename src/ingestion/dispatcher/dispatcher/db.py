import logging
import asyncio
import sqlite3
from pathlib import Path
import json
from inspect import isasyncgen

from .message import FEGAMessage

LOG = logging.getLogger(__name__)

def get_checksum(arr, alg):
    for d in arr:
        if d.get('type', None) == alg:
            return d.get('value', None)
    return None

def forward(func):
    async def wrapper(self, *args, **kwargs):
        async with self.lock: # need to avoid interleaving dispatched messages on the same connection
            try:
                cur = self.connection.cursor()
                cur.execute('BEGIN TRANSACTION;')
                gen = func(self, cur, *args, **kwargs)
                if isasyncgen(gen):
                    async for correlation_id, routing_key, message in gen:
                        if isinstance(message, FEGAMessage):
                            _message = message.content
                            correlation_id = message.correlation_id # reset
                        elif isinstance(message, str):
                            _message = message
                        else: # don't bother with bytes
                            _message = json.dumps(message, indent=4)
                            cur.execute('INSERT INTO messages(correlation_id, routing_key, message) VALUES(?,?,?)',
                                        (correlation_id, routing_key, _message))
                else:
                    await gen
                cur.execute('COMMIT;')
                self.event.set() # notify publisher loop
            except Exception as e:
                LOG.error('func %s raised %r', func.__name__, e, exc_info=True)
                cur.execute('ROLLBACK;')
                raise
    wrapper.__qualname__ = func.__qualname__
    wrapper.__name__ = func.__name__
    return wrapper

class DBConnection():
    """ Connection abstraction """

    __slots__ = (
        'path',
        'connection',
        'conf',
        'lock',
        'retry_after',
        'event'
    )

    def __init__(self, conf, conf_section='db'):
        self.connection = None
        self.conf = conf
        self.lock = asyncio.Lock()
        self.path = None
        self.event = asyncio.Event()
        self.retry_after = self.conf.getint(conf_section, 'retry_after', fallback=5)
        if self.retry_after <=0 :
            raise ValueError(f'Invalid "retry_after" in section [{conf_section}]')

        # Find the DB
        _here = Path(__file__).parent
        path = self.conf.get(conf_section, 'path')
        if not path:
            raise ValueError(f'Missing "path" section [{conf_section}]')
        p = None
        for p in [Path(path), _here / path, Path(conf.conf_file).parent / path]:
            if p.is_file():
                self.path = str(p.expanduser())
                break
        else:
            # not found => next to conf file
            self.path = str(p.expanduser())

        # Connect
        LOG.debug('Database: %s', self.path)
        self.connection = sqlite3.connect(self.path) # fail if not found
        self.connection.row_factory = sqlite3.Row
        # Ensure schema
        cur = self.connection.cursor()
        with open(_here / 'schema.sql') as f:
            cur.executescript(f.read())
        self.connection.commit()
        LOG.info('Database configured')
        
    def __str__(self):
        return str(self.connection) if self.connection else self.__class__.__name__

    def __repr__(self):
        return '<{0}: "{1}">'.format(self.__class__.__name__, str(self))

    async def close(self):
        if self.connection:
            self.connection.close()

    @forward
    async def do_ingest(self, cur, correlation_id, data):

        user = data['user']
        filepath = data['filepath']
        inbox_sha256 = get_checksum(data.get('encrypted_checksums', []), 'sha256')

        if inbox_sha256:
            # check if already ingested
            cur = self.connection.cursor()
            res = cur.execute('SELECT plaintext_sha256 FROM files WHERE inbox_sha256 = ?', (inbox_sha256,))
            r = res.fetchone()
            if r: # Gotcha
                assert r['plaintext_sha256']
                data['type'] = 'ingest' # do not reset to 'accession'
                data['decrypted_checksums'] = [{ 'type': 'sha256',
                                                 'value': r['plaintext_sha256'] }]
                yield (correlation_id, 'files.verified', data)
                # Note: we do not insert a row in the jobs table
                return

        # We try to insert
        try:
            res = cur.execute('''INSERT INTO jobs(correlation_id, username, filepath, inbox_sha256, status)
                                 VALUES(?,?,?,?,'ingesting')
                                 RETURNING id''', (correlation_id, user, filepath, inbox_sha256))
            r = cur.fetchone()
            data['internal'] = { 'job_id': r['id'], 'source': 'inserted' }
            yield (correlation_id, 'ingest', data)
            return # no need to try the other cases down there
        except sqlite3.IntegrityError as e:
            pass

        row = {'correlation_id': correlation_id,
               'user': user,
               'filepath': filepath,
               'inbox_sha256': inbox_sha256 }

        # Check the already inserted jobs
        # ===============================
        # if there is no plaintext_sha256, but there is an error: send again
        # otherwise => already in progress, return nothing
        res = cur.execute('''UPDATE jobs
                                SET error = NULL, -- reset
	                            status = 'ingesting' -- reset in case: cancelled
	                            -- should we reset the correlation_id and _inbox_sha256 ?
                             WHERE plaintext_sha256 IS NULL -- same as status = 'ingesting'
                               AND (error IS NOT NULL -- it has previously errored
	                            OR status NOT IN ('ingesting', 'archiving') -- ie cancelled or ingested
                                   )
                               AND ((username = :user AND filepath = :filepath) -- by username/filepath
                                    OR correlation_id = :correlation_id         -- by correlation id
                                   )
                             RETURNING id, correlation_id''', row)
        for r in res.fetchall():
            data['internal'] = { 'job_id': r['id'], 'source': 'retried'}
            yield (r['correlation_id'], 'ingest', data)

        # if there is plaintext_sha256, it was not inserted => already ingested
        res = cur.execute('''SELECT correlation_id, plaintext_sha256
                             FROM jobs
                             WHERE plaintext_sha256 IS NOT NULL
                               AND ((username = :user AND filepath = :filepath) -- by username/filepath
                                    OR correlation_id = :correlation_id         -- by correlation id
                                   ) -- might be also another user/filepath with same encrypted checksum
                          ''', row)
        for r in res.fetchall():
            data['decrypted_checksums'] = [{'type': 'sha256', 'value': r['plaintext_sha256'] }]
            yield (r['correlation_id'], 'files.verified', data)


    @forward
    async def do_ingestion_completed(self, cur, correlation_id, data):

        # Try to decrypt the header and insert the sha256 of the session key
        # since the table entries are unique, repetitions will be flagged (and rollbacked)
        # if there was no insertion, we raise an error
        # Note: let the KeyError happen
        internal = data['internal']
        job_id = int(internal['job_id']) # fail if missing
        plaintext_sha256 = internal['plaintext_sha256']
        header = internal['header'] # leave it hex
        session_keys = [ (sk, plaintext_sha256, str(job_id))
                         for sk in internal['sk_hashes'] if sk]

        assert job_id > 0, 'Invalid job_id'

        # catch empty header here rather than in crypt4gh.header_session_keys_sha256 function
        if not header: # should be at least 124 bytes
            cur.execute("UPDATE jobs SET error = 'Missing header' WHERE id = ?", (job_id,))
            raise ValueError('Missing header')

        if not session_keys: # user-error
            cur.execute("UPDATE jobs SET error = 'No session keys found in header' WHERE id = ?", (job_id,))
            data.pop('internal', None)
            data['type'] = 'error'
            data['reason'] = 'Crypt4GH decryption error'
            yield (correlation_id, 'files.error', data)
            return

        if not plaintext_sha256:
            cur.execute("UPDATE jobs SET error = 'Missing plaintext sha256' WHERE id = ?", (job_id,))
            raise ValueError('Missing plaintext sha256')

        # Check session keys
        try:
            res = cur.executemany('''INSERT INTO session_keys(sha256, plaintext_sha256, job_id)
                                     VALUES(?,?,?)''', session_keys)
        except sqlite3.IntegrityError as e:
            # Distinguish between:
            # * unique_violation => error (forward to user)
            # * not_null_violation or check_violation => error.system
            # A bit hackish, since both SQLITE_CONSTRAINT/SQLITE_MISMATCH return IntegrityError
            LOG.error('Integrity Error: %s', e, exc_info=True)
            reason = str(e)
            cur.execute("UPDATE jobs SET error = ? WHERE id = ?", (reason, job_id))
            if 'UNIQUE' in reason:
                data.pop('internal', None)
                data['type'] = 'error'
                data['reason'] = 'Crypt4GH encryption error: session keys not unique'
                yield (correlation_id, 'files.error', data)
                return

            raise ValueError(reason)


        row = {'payload_size': internal['payload_size'],
               'payload_sha256': internal['payload_sha256'],
               'plaintext_sha256': plaintext_sha256,
               'header': header,
               'inbox_sha256': internal['original_sha256'],
               'job_id': job_id,
               }

        # Otherwise save and send
        res = cur.execute('''UPDATE jobs
    	                        SET status = 'ingested',
	                            error = NULL, -- reset
	                            payload_size = :payload_size,
		                    payload_sha256 = :payload_sha256,
		                    header = :header,
		                    plaintext_sha256 = :plaintext_sha256,
		                    inbox_sha256 = :inbox_sha256 -- force it
                             WHERE id = :job_id
                             RETURNING correlation_id, username, filepath, inbox_sha256, plaintext_sha256''', row)
        for r in res.fetchall(): # should be one!
            message = {
                'type': 'ingest', # enforce message type
                'user': r['username'],
                'filepath': r['filepath'],
                'encrypted_checksums': [{ 'type': 'sha256', 'value': r['inbox_sha256'] }],
                'decrypted_checksums': [{ 'type': 'sha256', 'value': r['plaintext_sha256'] }],
            }
            yield (r['correlation_id'], 'files.verified', message)
 

    @forward
    async def do_cancel(self, cur, correlation_id, data):

        # Mark as 'cancelled' and republish to lega.ingestion
        # this will clean the staging area
        res = cur.execute('''INSERT INTO jobs(correlation_id, username, filepath, status)
                             VALUES(?,?,?, 'cancelled')
                             ON CONFLICT DO UPDATE SET status = 'cancelled'
                                                       -- , error = NULL -- don't reset, and keep trace
                             RETURNING id''', (correlation_id, data['user'], data['filepath']))
        r = cur.fetchone()
        data['internal'] = { 'job_id': r['id'], 'source': 'cancelled' }
        yield (correlation_id, 'cancel', data)


    @forward
    async def do_cancel_completed(self, cur, correlation_id, data):

        # When cancelling an already ingested file
        # job_id can't be missing
        job_id = int(data['internal']['job_id'])
        assert job_id > 0, "Invalid job id when cancelling"
        LOG.debug('Job %d cancelled, deleting from tables', job_id)
        cur.execute('''DELETE FROM jobs
                        WHERE id = ?
                          AND status = 'cancelled' -- in case we received another ingest in the meantime
                    ''', (job_id,) )
        cur.execute('''DELETE FROM session_keys
                        WHERE job_id = ?
                    ''', (job_id,) ) # The one with job_id = NULL are "reserved"


    @forward
    async def do_accession(self, cur, correlation_id, data):

        accession_id = data.get('accession_id')
        if not accession_id:
            raise ValueError('Missing accession_id')
        decrypted_checksums = data.get('decrypted_checksums', [])
        if not decrypted_checksums:
            raise ValueError('Missing decrypted_checksums')

        plaintext_sha256 = get_checksum(decrypted_checksums, 'sha256') # might be None

        # If already in files
        res = cur.execute('''SELECT accession_id, plaintext_sha256
                             FROM files
                             WHERE accession_id = ?
                                OR plaintext_sha256 = ?''', (accession_id, plaintext_sha256) ) # handles None
        r = res.fetchone()
        if r: # gotcha
            if r['accession_id'] != accession_id: # oh-oh
                data['type'] = 'error'
                data['reason'] = 'We already have an ingested file with this plaintext sha256, but a different accession_id'
                yield (correlation_id, 'files.error', data)
                return
            if plaintext_sha256 and r['plaintext_sha256'] != plaintext_sha256:
                data['type'] = 'error'
                data['reason'] = 'We already have an ingested file with this accession_id, but a different plaintext sha256'
                yield (correlation_id, 'files.error', data)
                return
            # otherwise, already ingested
            yield (correlation_id, 'files.completed', data)
            # The job will be deleted when cancel is finished
            data['type'] = 'cancel'
            yield (correlation_id, 'ingestion.cleanup', data) # go back to dispatcher
            return

        # Save info and forward to archiver
        if not plaintext_sha256:
            LOG.debug('decrypted_checksums: %s', decrypted_checksums)
            raise NotImplementedError('Only using sha256 for checksums')

        # if accession_id is set, and not the same => error
        res = cur.execute('''SELECT 1
                             FROM jobs
                             WHERE accession_id IS NOT NULL
                               AND accession_id != ?
	                       AND (plaintext_sha256 IS NOT NULL AND plaintext_sha256 = ?)''', (accession_id, plaintext_sha256) )
        r = res.fetchone()
        if r: # Forward the error to Central EGA
            data['type'] = 'error'
            data['reason'] = 'We already have an ingested file with this plaintext sha256, but a different accession_id'
            yield (correlation_id, 'files.error', data)
            return

        # Set the accession_id for all plaintext sha256
        cur.execute('''UPDATE jobs
                          SET accession_id = ?
                       WHERE plaintext_sha256 IS NOT NULL
                         AND plaintext_sha256 = ?''', (accession_id, plaintext_sha256) )

        # ... and cue music
        row = {'correlation_id': correlation_id,
               'user': data['user'],
               'filepath': data['filepath'],
               'accession_id': accession_id,
               }
        res = cur.execute('''UPDATE jobs
	                        SET status = 'archiving',
	                            error = NULL -- reset
                              WHERE (-- identify that job
	                             (username = :user AND filepath = :filepath)
	                             OR correlation_id = :correlation_id
     	                            )
	                        AND NOT EXISTS(SELECT 1 -- not if there is another archiving job, with no error
	                                       FROM jobs
	 		                       WHERE accession_id = :accession_id
	 		                         AND status = 'archiving'
			                         AND error IS NULL)
	                     RETURNING correlation_id, id, payload_sha256, payload_size''', row)

        for r in res.fetchall(): # should be only one!
            data['internal'] = {
                'payload_sha256': r['payload_sha256'], # re-encryption => probably unique
              	'payload_size': r['payload_size'],
               	'job_id': r['id'],
            }
            yield (r['correlation_id'], 'archive', data)


    @forward
    async def do_archival_completed(self, cur, correlation_id, data):

        internal = data['internal']
        job_id = int(internal['job_id'])
        accession_id = data['accession_id']
        relative_path = internal['relative_path']

        # This message should be received only once
        # Double-check job_id and accession_id/user/filepath

        res = cur.execute('SELECT * FROM jobs WHERE id = ?', (job_id,) )
        r = res.fetchone() # shouldn't be many

        assert accession_id == r['accession_id'], f"Different accession_id: {accession_id} =/= {r['accession_id']}"
        assert data['user'] == r['username'], "Different username than the job's one"
        assert data['filepath'] == r['filepath'], "Different filepath than the job's one"

        # Mark session key as "now used in the vault"
        cur.execute('UPDATE session_keys SET job_id = NULL WHERE job_id = ?', (job_id,) )

        # Tell the Vault-DB to save the info
        yield (r['correlation_id'], 'relay.vault.db', {
            'type': 'file.archived',
	    'accession_id': accession_id,
	    'payload_sha256': r['payload_sha256'],
            'payload_size': r['payload_size'],
            'header': r['header'], # DB will decrypt
	    'plaintext_sha256': r['plaintext_sha256'],
	    'relative_path': relative_path,
	    'inbox_sha256': r['inbox_sha256'],
	    'filepath': r['filepath'], # will extract filename, without .c4gh
        })

        # Save info to file, _after_ publishing to Vault-DB.
        # The Vault DB will also receive and decrypt the header
        # Let the UNIQUE constraint fail if needed
        cur.execute('''INSERT INTO files(accession_id,
                                         payload_size,payload_sha256,
                                         plaintext_sha256,inbox_sha256)
                       VALUES(?,?,?,?,?)''', (accession_id,
                                              r['payload_size'],
                                              r['payload_sha256'],
                                              r['plaintext_sha256'],
                                              r['inbox_sha256']))

        # Now handle the jobs with this same accession id
        # We accumulate a files.completed and a cancel for all other non-archived-but-ingested jobs
        # That includes the current one. The cancel will handle the DELETE FROM jobs.
        res = cur.execute('SELECT * FROM jobs WHERE accession_id = ?', (accession_id,) )
        for r in res.fetchall():
            # Clean up the message to send to Central EGA
            yield (r['correlation_id'], 'files.completed', {
	        'type': 'accession', # -- enforce message type
                'user': r['username'],
                'filepath': r['filepath'],
                'accession_id': r['accession_id'],
                'encrypted_checksums': [{ 'type': 'sha256', 'value': r['inbox_sha256'] }],
                'decrypted_checksums': [{ 'type': 'sha256', 'value': r['plaintext_sha256'] }],
            })
            # We also clean staging
            yield (r['correlation_id'], 'ingestion.cleanup', # go back to dispatcher
                   { 'type': 'cancel', # -- enforce message type
                     'user': r['username'],
                     'filepath': r['filepath'],
                     # 'internal': { 'job_id': r['id'] }
                    })


    # async def do_force_clean(self, cur, correlation_id, data):
    #     pass

    @forward
    async def do_error(self, cur, correlation_id, data):
        cur.execute('UPDATE jobs SET error = ? WHERE id = ?', (data['reason'], int(data['internal']['job_id'])))
        del data['internal']
        data['type'] = 'error' # not needed, but cleaner for Central EGA
        yield (correlation_id, 'files.error', data)



    async def publish_messages(self):

        cur = self.connection.cursor()
        LOG.info('Publishing from table "messages"')

        while True:
            await self.event.wait() # wait for "notifications"

            async with self.lock: # avoid asyncio interleaving
                res = cur.execute('SELECT id, correlation_id, routing_key, message FROM messages')
                results = res.fetchall()
                if not results:
                    self.event.clear()
                    continue

                LOG.debug('Publishing %d messages', len(results))
                published = []
                for row in results:
                    if await self.conf.mq.publish(row['correlation_id'], row['routing_key'], row['message']):
                        published.append((row['id'],))
                
                if published:
                    LOG.debug('Deleting %d messages', len(published))
                    cur.executemany('DELETE FROM messages WHERE id = ?', published)
                    self.connection.commit()
                self.event.clear()


    async def tick_forever(self):
        while True:
            await asyncio.sleep(self.retry_after)
            self.event.set()


