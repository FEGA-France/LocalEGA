import sys
import asyncio
import logging
import hashlib

from .. import conf
from . import load, ProgressBar

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":


   if len(sys.argv) < 3:
      print(f"Usage: {sys.argv[0]} <conf> <src>")
      sys.exit(1)

   logging.basicConfig(level=logging.DEBUG,
                       format='%(message)s')


   async def main(conf_file, src):

      config = conf.Configuration(conf_file, 'digester-posix-test')
      LOG.info('Config ready: %s', config)

      source = config.select_section('source')
      LOG.info('Source: %s', source)

      rctx = load(source)
        
      with rctx:
         rfile = rctx.open(src)

         async with rfile as r:

            LOG.debug("Filesize: %s bytes", r.size)
            tracer = ProgressBar("Checksuming", r.size)
                
            LOG.debug("Chunk size: %s bytes", r.CHUNK_SIZE)
            buf = bytearray(r.CHUNK_SIZE)

            sha256 = hashlib.sha256()

            while True:
               n = await r.readinto(buf)
               if n == 0:
                  break
               sha256.update(buf[:n])
               tracer.update(n)
            tracer.close()

            LOG.debug("Read %s bytes", r.bytes_read)
            LOG.debug("Checksum: %s", sha256.hexdigest())
                    
            if r.size != r.bytes_read:
               LOG.error("\tMissing bytes from: %s", src)


   loop = asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   #loop.set_debug(True)

   try:
      loop.run_until_complete(main(sys.argv[1], sys.argv[2]))
   except KeyboardInterrupt as e:
      LOG.warning('Cancelled')
      sys.exit(1)
