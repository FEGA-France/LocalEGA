/* #define DEBUG 3 */
/* #include "debug.h" */

#include <sys/statvfs.h>

#include "includes.h"

#include <endian.h> /* for be64toh */

int
ega_dist_db_getattr(fuse_ino_t ino, struct ega_config *data, struct stat *stbuf, int *is_dir)
__attribute__((nonnull))
{
  D1("Executing: %s [with $1 = %s, $2 = %lu]", data->getattr, data->username, ino);

  int err = 0;

  fuse_ino_t _ino = htobe64(ino);
  const char *const paramValues[2] = {data->username    , (char *) &_ino };
  const        int paramLengths[2] = {data->username_len, sizeof(_ino)   };
  const        int paramFormats[2] = {0                 , 1              };
  int resultFormat = 1; /* Binary results */

  int conn_id = ega_dist_db_acquire(data->pool, data->size, &data->lock, &data->cond);

  if (conn_id < 0)
    return 1;

  struct dbconn *c = &data->pool[conn_id];

  D2("Sending request");
  c->rows = PQexecParams(c->conn, data->getattr, 2, NULL,
			 paramValues, paramLengths, paramFormats, resultFormat);

  if (PQresultStatus(c->rows) != PGRES_TUPLES_OK) {
    D1("SQL error: %s", PQresultErrorMessage(c->rows));
    err = 1;
    goto bailout;
  }

  D2("Valid results");
  int nrows = PQntuples(c->rows), ncols = PQnfields(c->rows);

  if( ncols != 6 ){
    E("We should use 6 fields: We got %d", ncols);
    err = 2;
    goto bailout;
  }

  if( nrows == 0 ){
    D2("not found");
    err = 3;
    goto bailout;
  }

  time_t ctime, mtime; /* 8 bytes */

  // ctime: 0, mtime: 1, num_files : 2
  ctime = (time_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "ctime"))));
  mtime = (time_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "mtime"))));
  stbuf->st_nlink = (nlink_t)(uint32_t)ntohl(*((uint32_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "nlink"))));
  stbuf->st_size = (uint64_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "size"))));

  time_t now = time(NULL);
  struct timespec mt = { .tv_sec = mtime, .tv_nsec = 0L },
 	          at = { .tv_sec = now  , .tv_nsec = 0L },
	          ct = { .tv_sec = ctime, .tv_nsec = 0L };
  stbuf->st_mtim = mt;
  stbuf->st_atim = at;
  stbuf->st_ctim = ct;

  char* _is_dir = PQgetvalue(c->rows, 0, PQfnumber(c->rows, "is_dir"));
  //D1("is_dir: %s", (*_is_dir)? "yes" : "no");
  *is_dir = (*_is_dir)? 1 : 0;

  err = 0;
  
bailout:
  if(c->rows) PQclear(c->rows);
  ega_dist_db_release(data->pool, conn_id, &data->lock, &data->cond);
  return err;
}

int
ega_dist_db_readdir(fuse_ino_t ino, struct dbconn *c, struct ega_config *data)
__attribute__((nonnull))
{
  D1("Executing: %s [with $1 = %s, $2 = %lu]", data->readdir, data->username, ino);

  int err = 0;

  fuse_ino_t _ino = htobe64(ino);
  const char *const paramValues[2] = {data->username    , (char *) &_ino };
  const        int paramLengths[2] = {data->username_len, sizeof(_ino)   };
  const        int paramFormats[2] = {0                 , 1              };

  int resultFormat = 1; /* Binary format */

  D2("Sending request");
  c->rows = PQexecParams(c->conn, data->readdir, 2, NULL,
			paramValues, paramLengths, paramFormats, resultFormat);

  if (PQresultStatus(c->rows) != PGRES_TUPLES_OK) {
    D1("SQL error: %s", PQresultErrorMessage(c->rows));
    return 1;
  }

  int ncols = PQnfields(c->rows);
  //ino, display_name, ctime, mtime, nlink, size, decrypted_filesize, is_dir
  if( ncols != 8 ){
    E("We should use 8 fields: We got %d", ncols);
    return 2;
  }

  return 0;
}

int
ega_dist_db_lookup(fuse_ino_t parent, const char* name,
		   struct ega_config *data,
		   struct fuse_entry_param *e, int *is_dir)
__attribute__((nonnull))
{
  D1("Executing: %s [with $1 = %s, $2 = %lu, $3 = %s]", data->lookup, data->username, parent, name);

  int err = 0;

  fuse_ino_t _ino = htobe64(parent);
  const char *const paramValues[3] = {data->username    , (char *) &_ino, name         };
  const        int paramLengths[3] = {data->username_len, sizeof(_ino)  , strlen(name) };
  const        int paramFormats[3] = {0                 , 1             , 0            };
  int resultFormat = 1; /* Binary results */

  int conn_id = ega_dist_db_acquire(data->pool, data->size, &data->lock, &data->cond);

  if (conn_id < 0)
    return 1;

  struct dbconn *c = &data->pool[conn_id];

  D2("Sending request");
  c->rows = PQexecParams(c->conn, data->lookup, 3, NULL,
			paramValues, paramLengths, paramFormats, resultFormat);
  
  if (PQresultStatus(c->rows) != PGRES_TUPLES_OK) {
    D1("SQL error: %s", PQresultErrorMessage(c->rows));
    err = 1;
    goto bailout;
  }

  D2("Valid results");
  int nrows = PQntuples(c->rows), ncols = PQnfields(c->rows);
  //ino, ctime , mtime, nlink, size, decrypted_filesize, is_dir
  if( ncols != 7 ){
    E("We should use 7 fields: We got %d", ncols);
    err = 2;
    goto bailout;
  }

  if( nrows == 0 ){
    err = 3;
    goto bailout;
  }

  /* Parse the result */
  e->ino = (fuse_ino_t)be64toh(*((fuse_ino_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "ino"))));  
  e->attr.st_ino   = e->ino;
  e->attr.st_nlink = (nlink_t)(uint32_t)ntohl(*((uint32_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "nlink"))));
  e->attr.st_size  = (uint64_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "size"))));

  char* _is_dir = PQgetvalue(c->rows, 0, PQfnumber(c->rows, "is_dir"));
  D1("is_dir: %s", (*_is_dir)? "yes" : "no");

  time_t ctime, mtime; /* 8 bytes */
  ctime = (time_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "ctime"))));
  mtime = (time_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "mtime"))));
  time_t now = time(NULL);
  struct timespec mt = { .tv_sec = mtime, .tv_nsec = 0L },
 	          at = { .tv_sec = now  , .tv_nsec = 0L },
	          ct = { .tv_sec = ctime, .tv_nsec = 0L };
  e->attr.st_mtim = mt;
  e->attr.st_atim = at;
  e->attr.st_ctim = ct;

  *is_dir = (*_is_dir)? 1 : 0;

  char* decrypted_file = PQgetvalue(c->rows, 0, PQfnumber(c->rows, "decrypted_file"));
  if(decrypted_file)
    ega_cache_put(e->ino, decrypted_file);

  err = 0;
bailout:
  if(c->rows) PQclear(c->rows);
  ega_dist_db_release(data->pool, conn_id, &data->lock, &data->cond);
  return err;
}


int
ega_dist_db_file_info(fuse_ino_t ino,
		      struct ega_config *data,
		      int(*process_file_info)(const char* filepath, uint8_t *header, unsigned int header_size)
		      )
__attribute__((nonnull))
{
  D1("Executing: %s [with $1 = %s, $2 = %lu]", data->file_info, data->username, ino);

  int err = 0;

  fuse_ino_t _ino = htobe64(ino);
  const char *const paramValues[2] = {data->username    , (char *) &_ino };
  const        int paramLengths[2] = {data->username_len, sizeof(_ino)   };
  const        int paramFormats[2] = {0                 , 1              };
  int resultFormat = 1; /* binary output */

  int conn_id = ega_dist_db_acquire(data->pool, data->size, &data->lock, &data->cond);

  if (conn_id < 0)
    return 1;

  struct dbconn *c = &data->pool[conn_id];

  D2("Sending request");
  c->rows = PQexecParams(c->conn, data->file_info, 2, NULL,
			paramValues, paramLengths, paramFormats, resultFormat);

  if (PQresultStatus(c->rows) != PGRES_TUPLES_OK) {
    D1("SQL status: %s", PQresStatus(PQresultStatus(c->rows)));
    D1("SQL error: %s", PQresultErrorMessage(c->rows));
    err = 1;
    /* if(PQresultStatus(c->rows) == PGRES_FATAL_ERROR) */
    /*   errno = EPERM; */
    /* else */
    /*   errno = ENOENT; */
    goto bailout;
  }

  D2("Valid results");
  int nrows = PQntuples(c->rows), ncols = PQnfields(c->rows);
  if( ncols != 2 ){
    E("We should use 2 fields: We got %d", ncols);
    err = 2;
    errno = EINVAL;
    goto bailout;
  }

  if( nrows == 0 ){
    err = 3;
    goto bailout;
  }

  // order: filepath, header
  if(PQgetisnull(c->rows, 0, 0) || PQgetisnull(c->rows, 0, 1)){
    err = 4;
    /* errno = EPERM; */
    goto bailout;
  }

  err = process_file_info((char*)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "filepath")),  /* NULL-terminated filepath */
			  (uint8_t*)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "header")), /* header */
			  PQgetlength(c->rows, 0, PQfnumber(c->rows, "header"))           /* header length */
			  );
bailout:
  if(c->rows) PQclear(c->rows);
  ega_dist_db_release(data->pool, conn_id, &data->lock, &data->cond);
  return err;
}

int
ega_dist_db_getxattr(fuse_ino_t ino,
		     struct ega_config *data,
		     const char* name,
		     int(*process_xattr)(const char* value, size_t size)
		      )
__attribute__((nonnull))
{

  if(!data->getxattr){
    errno = ENOTSUP;
    return 1;
  }

  /* check the cache first */
  int with_cache = !strncmp(name, "user.decrypted_filesize", sizeof("user.decrypted_filesize") - 1);
  char* value = NULL;
  if(with_cache){
    value = ega_cache_get(ino);
    if(value) 
      return process_xattr(value, strlen(value));
  }

  D1("Executing: %s [with $1 = %s, $2 = %lu]", data->getxattr, data->username, ino);

  int err = 0;

  fuse_ino_t _ino = htobe64(ino);
  const char *const paramValues[3] = {data->username    , (char *) &_ino, name        };
  const        int paramLengths[3] = {data->username_len, sizeof(_ino)  , strlen(name)};
  const        int paramFormats[3] = {0                 , 1             , 0           };
  int resultFormat = 1; /* binary output */

  int conn_id = ega_dist_db_acquire(data->pool, data->size, &data->lock, &data->cond);

  if (conn_id < 0)
    return 1;

  struct dbconn *c = &data->pool[conn_id];

  D2("Sending request");
  c->rows = PQexecParams(c->conn, data->getxattr, 3, NULL,
			paramValues, paramLengths, paramFormats, resultFormat);

  if (PQresultStatus(c->rows) != PGRES_TUPLES_OK) {
    D1("SQL status: %s", PQresStatus(PQresultStatus(c->rows)));
    D1("SQL error: %s", PQresultErrorMessage(c->rows));
    err = 1;
    /* if(PQresultStatus(c->rows) == PGRES_FATAL_ERROR) */
    /*   errno = EPERM; */
    /* else */
    /*   errno = ENOENT; */
    goto bailout;
  }

  D2("Valid results");
  int nrows = PQntuples(c->rows), ncols = PQnfields(c->rows);
  if( ncols != 1 ){
    E("We should return 1 value: We got %d", ncols);
    err = 2;
    errno = EINVAL;
    goto bailout;
  }

  if( nrows == 0 ){
    err = 3;
    goto bailout;
  }

  if(PQgetisnull(c->rows, 0, 0)){
    err = 4;
    /* errno = EPERM; */
    goto bailout;
  }

  value = (char*)PQgetvalue(c->rows, 0, 0); /* NULL-terminated value */
  size_t vsize = PQgetlength(c->rows, 0, 0);      /* value length */

  err = process_xattr(value, vsize);

  /* cache regardless of error */
  if(with_cache)
    ega_cache_put(ino, value);


bailout:
  if(c->rows) PQclear(c->rows);
  ega_dist_db_release(data->pool, conn_id, &data->lock, &data->cond);
  return err;
}


int
ega_dist_db_statfs(fuse_ino_t ino, struct ega_config *data, struct statvfs *stbuf)
__attribute__((nonnull))
{
  D1("Executing: %s [with $1 = %s, $2 = %lu]", data->statfs, data->username, ino);

  int err = 0;

  fuse_ino_t _ino = htobe64(ino);
  const char *const paramValues[2] = {data->username    , (char *) &_ino };
  const        int paramLengths[2] = {data->username_len, sizeof(_ino)   };
  const        int paramFormats[2] = {0                 , 1              };
  int resultFormat = 1; /* Binary results */

  int conn_id = ega_dist_db_acquire(data->pool, data->size, &data->lock, &data->cond);

  if (conn_id < 0)
    return 1;

  struct dbconn *c = &data->pool[conn_id];

  D2("Sending request");
  c->rows = PQexecParams(c->conn, data->statfs, 2, NULL,
			 paramValues, paramLengths, paramFormats, resultFormat);

  if (PQresultStatus(c->rows) != PGRES_TUPLES_OK) {
    D1("SQL error: %s", PQresultErrorMessage(c->rows));
    err = 1;
    goto bailout;
  }

  D2("Valid results");
  int nrows = PQntuples(c->rows), ncols = PQnfields(c->rows);

  // ctime double precision, mtime double precision, nlink int4, size int8, is_dir boolean

  if( ncols != 2 ){
    E("We should use 2 fields: We got %d", ncols);
    err = 2;
    goto bailout;
  }

  if( nrows == 0 ){
    D2("not found");
    err = 3;
    goto bailout;
  }

  /* See https://man7.org/linux/man-pages/man2/statvfs.2.html
     struct statvfs {
               unsigned long  f_bsize;    // Filesystem block size
               unsigned long  f_frsize;   // Fragment size
               fsblkcnt_t     f_blocks;   // Size of fs in f_frsize units
               fsblkcnt_t     f_bfree;    // Number of free blocks
               fsblkcnt_t     f_bavail;   // Number of free blocks for unprivileged users
               fsfilcnt_t     f_files;    // Number of inodes
               fsfilcnt_t     f_ffree;    // Number of free inodes
               fsfilcnt_t     f_favail;   // Number of free inodes for unprivileged users
               unsigned long  f_fsid;     // Filesystem ID
               unsigned long  f_flag;     // Mount flags
               unsigned long  f_namemax;  // Maximum filename length
           };


	   But only the following fields seem used:
	   f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, f_files, f_ffree, f_namemax
  */

  stbuf->f_bsize = 1;
  stbuf->f_frsize = 1;
  stbuf->f_blocks = ((uint64_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "size")))));
  stbuf->f_bfree = 0;
  stbuf->f_bavail = 0;
  stbuf->f_files = 200000000000; /* EGAD + EGAF */
  stbuf->f_ffree = stbuf->f_files - (uint64_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, 0, PQfnumber(c->rows, "files"))));;
  stbuf->f_namemax = 255;

  err = 0;
  
bailout:
  if(c->rows) PQclear(c->rows);
  ega_dist_db_release(data->pool, conn_id, &data->lock, &data->cond);
  return err;
}
