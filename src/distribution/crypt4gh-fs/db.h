#ifndef __EGA_DIST_DB_INCLUDED__
#define __EGA_DIST_DB_INCLUDED__ 1

struct dbconn {
  const char* conninfo;
  PGconn* conn;
  PGresult* rows;
  int busy; /* will store the thread id */
};


int ega_dist_db_getattr(fuse_ino_t ino, struct ega_config *data, struct stat *stbuf, int *is_dir);

int ega_dist_db_readdir(fuse_ino_t ino, struct dbconn *c, struct ega_config *data);

int ega_dist_db_lookup(fuse_ino_t parent, const char* name, struct ega_config *data,
		       struct fuse_entry_param *e, int *is_dir);


int ega_dist_db_file_info(fuse_ino_t ino, struct ega_config *data,
			  int(*process_file_info)(const char* filepath, uint8_t *header, unsigned int header_size)
			  );

int ega_dist_db_getxattr(fuse_ino_t ino,
			 struct ega_config *data,
			 const char* name,
			 int(*process_xattr)(const char* value, size_t size)
			 );

int ega_dist_db_statfs(fuse_ino_t ino, struct ega_config *data, struct statvfs *stbuf);

#endif /* ! __EGA_DIST_DB_INCLUDED__ */
