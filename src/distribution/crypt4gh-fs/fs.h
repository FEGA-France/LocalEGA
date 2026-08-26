#ifndef __EGA_DIST_FS_INCLUDED__
#define __EGA_DIST_FS_INCLUDED__ 1

#include <sys/types.h>

struct ega_config {
  char* buffer;

  /* current user */
  uid_t uid;
  gid_t gid;
  char* username;
  size_t username_len;
  time_t mounted_at;

  int conf_fd;
  int parent_fd;
  char* mountpoint;

  int show_help;
  int show_version;
  int foreground;
  int singlethread;
  int clone_fd;
  unsigned int max_idle_threads;


  /* database configuration */
  char *conninfo;	/* connection info as used in PQconnectdb */
  struct dbconn* pool;
  unsigned int size;
  pthread_mutex_t lock; /* monitor lock */
  pthread_cond_t cond;  /* condition signalling a free connection */

  /* DB queries */
  char* lookup;
  char* readdir;
  char* getattr;
  char* file_info;
  char* getxattr;
  char* statfs;
};

#endif /* ! __EGA_DIST_FS_INCLUDED__ */
