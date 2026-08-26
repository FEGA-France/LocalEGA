/* #define DEBUG 3 */
/* #include "debug.h" */

#include "includes.h"

#include <sys/types.h>
#include <unistd.h>

#define MAX_NUM_LEN         20
//#define MAX_NUM_LEN (sizeof(ULLONG_MAX) - 1) /* Gee... insanely large numbers!! */

#define DEFAULT_ENTRY_TIMEOUT 300.0
#define DEFAULT_ATTR_TIMEOUT 300.0


static void
ega_dist_getattr(fuse_req_t req, fuse_ino_t ino,
		 struct fuse_file_info *fi)
{
  D1("getattr: inode %lu", ino);

  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data)
    return (void) fuse_reply_err(req, EINVAL);  

  struct stat s;

  if( ino == FUSE_ROOT_ID ){ /* It's the root directory itself */
    s.st_ino = ino;
    s.st_uid = data->uid;
    s.st_gid = data->gid;
    s.st_mode = S_IFDIR | 0500;
    s.st_nlink = 1;
    s.st_size = 0;
    //s.st_blksize = 512;     /* Block size for filesystem I/O */
    //s.st_blocks = 1;        /* Number of 512B blocks allocated */

    time_t now = time(NULL);
    struct timespec mt = { .tv_sec = data->mounted_at, .tv_nsec = 0L },
                    at = { .tv_sec = now             , .tv_nsec = 0L },
	            ct = { .tv_sec = data->mounted_at, .tv_nsec = 0L };
    s.st_mtim = mt;
    s.st_atim = at;
    s.st_ctim = ct;
    return (void) fuse_reply_attr(req, &s, DEFAULT_ATTR_TIMEOUT);
  }

  /* Get the attr from the database */
  int is_dir;
  if(ega_dist_db_getattr(ino, data, &s, &is_dir))
      return (void) fuse_reply_err(req, ENOENT);

  //s.st_blksize = 512;     /* Block size for filesystem I/O */
  //s.st_blocks = 1;        /* Number of 512B blocks allocated */

  if(is_dir)
    s.st_mode = S_IFDIR | 0500;
  else
    s.st_mode = S_IFREG | 0400;

  return (void) fuse_reply_attr(req, &s, DEFAULT_ATTR_TIMEOUT);
}


static void
ega_dist_lookup(fuse_req_t req, fuse_ino_t inode_p, const char *name)
__attribute__((nonnull(3)))
{
  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data || !name)
    return (void) fuse_reply_err(req, EINVAL);  

  struct fuse_entry_param e;
  memset(&e, 0, sizeof(e));
  e.attr_timeout = DEFAULT_ATTR_TIMEOUT;
  e.entry_timeout = DEFAULT_ENTRY_TIMEOUT;

  e.attr.st_uid = data->uid;
  e.attr.st_gid = data->gid;

  int is_dir;
  if(ega_dist_db_lookup(inode_p, name, data, &e, &is_dir))
      return (void) fuse_reply_err(req, ENOENT);

  if(is_dir)
    e.attr.st_mode = S_IFDIR | 0500;
  else
    e.attr.st_mode = S_IFREG | 0400;

  return (void) fuse_reply_entry(req, &e);
}

/* ============ 

   Directories

   When opening the dir, we make _one_ call to the database,
   getting all the listing (passing limit NULL),
   and we save the PG results struct.
   When doing a readdir, we fill up the given buffer with rows for the PG result and shift the offset.
   Finally, on release, we clean the PG result struct.

   We use readdir_plus, because we can then pass the entire struct stat instead of just { .ino, .st_mode}
   (only using the bits 12-15, ie reg file or directory). That latter would cause a getattr for each entry.

   ============ */

static void
ega_dist_opendir(fuse_req_t req, fuse_ino_t ino,
		 struct fuse_file_info *fi)
{

  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data)
    return (void) fuse_reply_err(req, EINVAL);
  int conn_id = ega_dist_db_acquire(data->pool, data->size, &data->lock, &data->cond);

  if (conn_id < 0)
    return (void) fuse_reply_err(req, EIO);

  D1("Using DB connection %d", conn_id);
  fi->fh = (uintptr_t)conn_id;

  struct dbconn *conn = &data->pool[conn_id];

  if(ega_dist_db_readdir(ino, conn, data))
    return (void) fuse_reply_err(req, (errno)?errno:EPERM);

  D2("with %d entries", PQntuples(conn->rows));
  fuse_reply_open(req, fi);
}

static void
ega_dist_releasedir(fuse_req_t req, fuse_ino_t ino, struct fuse_file_info *fi)
{
  D1("Closing directory %lu", ino);
  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data)
    return (void) fuse_reply_err(req, EINVAL);
  unsigned int conn_id = (unsigned int)fi->fh;
  struct dbconn *c = &data->pool[conn_id];

  if(c->rows) PQclear(c->rows);
  ega_dist_db_release(data->pool, conn_id, &data->lock, &data->cond);

  fuse_reply_err(req, errno);
}


static void
ega_dist_readdir_plus(fuse_req_t req, fuse_ino_t ino, size_t size,
		      off_t offset, struct fuse_file_info *fi)
{

  int err = 1;
  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data)
    return (void) fuse_reply_err(req, EINVAL);

  struct dbconn *c = &data->pool[(unsigned int)fi->fh];

  int nrows = PQntuples(c->rows);
  off_t count = nrows - offset;
  D1("readdir | size  : %zu | offset: %zu | left: %ld", size, offset, count);

  char *buf = NULL;
  char *p;
  size_t remainder = size;
  size_t entsize = 0;

  if(count == 0){ err = 0; goto bailout; /* over */ }

  count = 0; /* repurpose */

  D3("Allocating buffer of size: %zu", size);
  buf = calloc(1, size);
  if (!buf) { err = 1; /* errno = ENOMEM; */ goto bailout; }
  p = buf;

  struct fuse_entry_param e;
  memset(&e, 0, sizeof(e));
  e.attr_timeout = DEFAULT_ATTR_TIMEOUT;
  e.entry_timeout = DEFAULT_ENTRY_TIMEOUT;

  char *display_name;
  time_t ctime, mtime; /* 8 bytes */
  time_t now = time(NULL);
  char *decrypted_filesize;

  while(offset < nrows){

    // ino int8, display_name text, ctime double precision, mtime double precision, nlink int4, size int8, is_dir boolean
    e.ino = (fuse_ino_t)be64toh(*((fuse_ino_t *)PQgetvalue(c->rows, offset, PQfnumber(c->rows, "ino"))));
    e.attr.st_ino   = e.ino;
    e.attr.st_nlink = (nlink_t)(uint32_t)ntohl(*((uint32_t *)PQgetvalue(c->rows, offset, PQfnumber(c->rows, "nlink"))));
    e.attr.st_size  = (uint64_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, offset, PQfnumber(c->rows, "size"))));

    char* _is_dir = PQgetvalue(c->rows, offset, PQfnumber(c->rows, "is_dir"));
    D1("is_dir: %s", (*_is_dir)? "yes" : "no");

    e.attr.st_mode = (*_is_dir)? (S_IFDIR | 0500) : (S_IFREG | 0400);

    ctime = (time_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, offset, PQfnumber(c->rows, "ctime"))));
    mtime = (time_t)be64toh(*((uint64_t *)PQgetvalue(c->rows, offset, PQfnumber(c->rows, "mtime"))));
    struct timespec mt = { .tv_sec = mtime, .tv_nsec = 0L },
                    at = { .tv_sec = now  , .tv_nsec = 0L },
                    ct = { .tv_sec = ctime, .tv_nsec = 0L };
    e.attr.st_mtim = mt;
    e.attr.st_atim = at;
    e.attr.st_ctim = ct;

    e.attr.st_uid = data->uid;
    e.attr.st_gid = data->gid;

    display_name = PQgetvalue(c->rows, offset, PQfnumber(c->rows, "display_name"));

    decrypted_filesize = PQgetvalue(c->rows, offset, PQfnumber(c->rows, "decrypted_filesize")); /* NULL-terminated */
    if(decrypted_filesize)
      ega_cache_put(e.ino, decrypted_filesize);

    /* add the entry to the buffer and check size */
    offset++;
    entsize = fuse_add_direntry_plus(req, p, remainder, display_name, &e, offset); /* next offset */
    D3("entsize: %zu | remainder: %zu | size: %zu", entsize, remainder, size);
    if (entsize > remainder) { /* Not added to the buffer, no space */
      break; /* buffer full, not an error */
    }
    p += entsize;
    remainder -= entsize;
    count++;
  }
  err = 0;
  D2("Processed %ld entries", count);

bailout:
  if (err && remainder == size){
    E("----------------------- There is an error: %d | remainder: %zu | errno: %d", err, remainder, errno);
    fuse_reply_err(req, (errno)?errno:ENOENT);
  } else {
    fuse_reply_buf(req, buf, size - remainder);
  }
  free(buf);
}

/* ============ 

   Opening a Crypt4GH file

   We get the header from the database while opening the file.
   We prepend the header in its own buffer, if the offset is 0.
   Else we send the payload (no need to shift, expect in the first call).
   Let's hope the first call is larger than the header.

   ============ */

struct ega_file_info {
  int fd;
  uint8_t* header;
  size_t header_size;
};

static void
ega_dist_open(fuse_req_t req, fuse_ino_t ino, struct fuse_file_info *fi)
{
  D1("open | ino=%lu | flags=%d", ino, fi->flags);

  /* No write */
  if( fi->flags & O_RDWR || fi->flags & O_WRONLY)
    return (void)fuse_reply_err(req, EPERM);

  struct ega_file_info *egafi = calloc(1, sizeof(struct ega_file_info));
  if (egafi == NULL)
    return (void) fuse_reply_err(req, ENOMEM);

  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data)
    return (void) fuse_reply_err(req, EINVAL);

  int err = 1;
  int process_file_info(const char* filepath, uint8_t *header, unsigned int header_size){
    D3("filepath     : %s", filepath);
    D3("header_size  : %u", header_size);

    if (!filepath || !header || header_size == 0){
      errno = EPERM;
      return 1;
    }

    int fd = open(filepath, fi->flags & ~O_NOFOLLOW);
    if (fd == -1){
      errno = ENOENT;
      return 2;
    }

    egafi->fd = fd;
    egafi->header_size = header_size;
    egafi->header = calloc(header_size, sizeof(uint8_t));
    if (egafi->header == NULL){
      errno = ENOMEM;
      return 3;
    }
    memcpy(egafi->header, header, header_size);
    return 0;
  }

  err = ega_dist_db_file_info(ino, data, &process_file_info);

  if(err){
    free(egafi);
    int e = (errno)?errno:EPERM;
    E("Error opening the file %lu: [%d] %s", ino, err, strerror(e));
    return (void) fuse_reply_err(req, e);
  }

  fi->fh = (uint64_t)egafi;
  fi->direct_io = 1;  /* never cache */
  fi->keep_cache = 0;
  fuse_reply_open(req, fi);
}

static void
ega_dist_release(fuse_req_t req, fuse_ino_t ino, struct fuse_file_info *fi)
{
  D1("release inode %lu", ino);
  struct ega_file_info *egafi = (struct ega_file_info *)fi->fh;
  if(egafi){
    if(egafi->fd > 0) close(egafi->fd);
    if(egafi->header) free(egafi->header);
    free(egafi);
  }
  fuse_reply_err(req, 0);
}

struct fuse_bufvec2 {
  size_t count;
  size_t idx;
  size_t off;
  struct fuse_buf buf[2];
};

static void
ega_dist_read(fuse_req_t req, fuse_ino_t ino, size_t size,
	      off_t offset, struct fuse_file_info *fi)
{
  struct ega_file_info *egafi = (struct ega_file_info *)fi->fh;

  D1("read called on inode: %lu | offset: %zu | size: %zu", ino, offset, size);

  /* if(offset == 0){ */
  D3("read called on inode: %lu, flags: %d", ino, fi->flags);
  D3("offset: %zu | size: %zu | header size: %lu", offset, size, egafi->header_size);
  /* } */

  if (offset < egafi->header_size){

    if ( offset + size < egafi->header_size ){
      /* Not asking for much data */
      struct fuse_bufvec buf = FUSE_BUFVEC_INIT(size);
      buf.buf[0].mem = egafi->header + offset;
      buf.buf[0].pos = 0;
      fuse_reply_data(req, &buf, FUSE_BUF_SPLICE_MOVE);

    } else {
      /* Asking for the header _and_ some more data */
      struct fuse_bufvec2 buf = {
	.count = 2,
	.idx = 0,
	.off = 0,
	.buf = {
	  { .size = egafi->header_size - offset,
	    .flags = 0,
	    .mem = egafi->header + offset,
	    .fd = -1,
	    .pos = 0,
	  },
	  { .size = size - (egafi->header_size - offset),
	    .flags = FUSE_BUF_IS_FD | FUSE_BUF_FD_SEEK, /* we don't use FUSE_BUF_FD_RETRY */
	    .fd = egafi->fd,
	    .pos = 0,
	  }
	}
      };

      fuse_reply_data(req, (struct fuse_bufvec*)&buf, FUSE_BUF_SPLICE_MOVE);
    }

  } else {
    /* header already sent, sending now the payload, until EOF */
    struct fuse_bufvec buf = FUSE_BUFVEC_INIT(size); /* might be more than what's left in the FD */
    buf.buf[0].flags = FUSE_BUF_IS_FD | FUSE_BUF_FD_SEEK; /* we don't use FUSE_BUF_FD_RETRY */
    buf.buf[0].fd = egafi->fd;
    buf.buf[0].pos = offset - egafi->header_size;
    fuse_reply_data(req, &buf, FUSE_BUF_SPLICE_MOVE);
  }

}


static void
ega_dist_getxattr(fuse_req_t req, fuse_ino_t ino, const char *name, size_t size)
{
  if(ino < 200000000000)
    return (void) fuse_reply_err(req, ENODATA);

  if (size == 0)
    return (void)fuse_reply_xattr(req, 32); /* large enough to the the digits of max uint64_t (2^65 - 1) */

  D1("getxattr | ino=%lu | name: %s | size=%zu", ino, name, size);

  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data)
    return (void) fuse_reply_err(req, EINVAL);

  int process_xattr(const char* value, size_t vsize){
    D1("value : %s", value);
    D1("vsize : %zu", vsize);

    if(size < vsize)
      fuse_reply_err(req, ERANGE); /* should not happen */
    else {
      fuse_reply_buf(req, value, vsize);
    }
    return 0;
  }

  int err = ega_dist_db_getxattr(ino, data, name, &process_xattr);

  if(err){
    int e = (errno)?errno:ENODATA;
    E("Error getxattr on file %lu for attr %s: [%d] %s", ino, name, err, strerror(e));
    return (void) fuse_reply_err(req, e);
  }

}

static void
ega_dist_listxattr(fuse_req_t req, fuse_ino_t ino, size_t size)
{
  /* no extended attributes for datasets */
  if(ino < 200000000000)
    return (void) fuse_reply_buf(req, "", 1);

  /* extended attributes for files: only "user.decrypted_filesize" */

  D1("listxattr | ino=%lu | size=%zu", ino, size);
  int vsize = sizeof("user.decrypted_filesize\0user.dataset_stable_id\0user.stable_id"); // null-terminated

  if (size) {
    if(size < vsize)
      fuse_reply_err(req, ERANGE);
    else
      fuse_reply_buf(req, "user.decrypted_filesize\0user.dataset_stable_id\0user.stable_id", vsize);
  } else {
    fuse_reply_xattr(req, vsize);
  }
}


static void
ega_dist_statfs(fuse_req_t req, fuse_ino_t ino)
{
  D1("STATFS inode: %lu", ino);

  struct ega_config *data = (struct ega_config *) fuse_req_userdata(req);
  if (!data)
    return (void) fuse_reply_err(req, EINVAL);  

  struct statvfs buf;
  memset(&buf, 0, sizeof(buf));

  if(ega_dist_db_statfs(ino, data, &buf))
    fuse_reply_err(req, ENOSYS);
  else
    fuse_reply_statfs(req, &buf);
}

static void
ega_dist_init(void *userdata, struct fuse_conn_info *conn)
{
  D1("Initializing the file system");
  struct ega_config *data = (struct ega_config *)userdata;

  if( !data ||
      ega_dist_db_init(data->conninfo,
		       &data->pool, data->size,
		       &data->lock, &data->cond) )
    {
      E("Allocating database connection pool failed!");
      E("Aborting...");
      exit( EXIT_FAILURE );
    }
  D2("File system initialized with %u DB connections", data->size);

  ega_cache_init();
}

static void
ega_dist_destroy(void *userdata)
{
  D1("Destroying the file system");
  struct ega_config *data = (struct ega_config *)userdata;
  if(data)
    ega_dist_db_terminate(data->pool, data->size,
			  &data->lock, &data->cond);

  ega_cache_destroy();
}

const struct fuse_lowlevel_ops ega_dist_operations = {
	.init		= ega_dist_init,
	.destroy	= ega_dist_destroy,
	.lookup		= ega_dist_lookup,
	.getattr	= ega_dist_getattr,
	.opendir	= ega_dist_opendir,
	.readdirplus	= ega_dist_readdir_plus, /* using the full struct stat and not the upper 12 bits of st_mode */
	.releasedir	= ega_dist_releasedir,
	.open		= ega_dist_open,
	.release	= ega_dist_release,
	.read		= ega_dist_read,
	.statfs		= ega_dist_statfs,
	.getxattr	= ega_dist_getxattr,
	.listxattr	= ega_dist_listxattr,
};
