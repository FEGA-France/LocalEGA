/**********************************************************************************
 * Read-only Crypt4GH file system, listing information from an SQLite "database".
 *
 *  Author:  Frédéric Haziza <silverdaz@gmail.com>
 *    Date:  November 2024
 *
 *  This program can be distributed under the terms of the GNU Affero GPL.
 *  See the LICENSE file.
 **********************************************************************************/

#pragma once

#define _GNU_SOURCE /* avoid implicit declaration of *pt* functions */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#ifndef PACKAGE_VERSION
#define PACKAGE_VERSION "2.0"
#endif

#ifndef FUSE_USE_VERSION
#define FUSE_USE_VERSION FUSE_MAKE_VERSION(3, 14)
#endif

#include <fuse_lowlevel.h>

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <pthread.h>
#include <netdb.h>
#include <signal.h>
#include <sys/uio.h>
#include <sys/types.h>
#include <sys/time.h>
#include <sys/mman.h>
#include <limits.h>
#include <strings.h>
#include <sys/stat.h>

#include <sys/sysmacros.h> /* feature_test_macros for major/minor(st_dev) */
#include <ctype.h>
#include <pwd.h>
#include <grp.h>
#include <sys/resource.h>
#include <sys/mount.h>

/* reset STATX */
#if FUSE_MAJOR_VERSION < 3 || \
    (FUSE_MAJOR_VERSION == 3 && FUSE_MINOR_VERSION < 18)
#undef HAVE_STATX
#endif

#ifdef HAVE_STATX
#include <sys/statvfs.h>
#endif

#define OFF_FMT "%lu"
#define INO_FMT "%lu"

#ifndef _PATH_TTY
# define _PATH_TTY "/dev/tty"
#endif

/* #if !defined(__GNUC__) || (__GNUC__ < 2) */
/* # define __attribute__(x) */
/* #endif /\* !defined(__GNUC__) || (__GNUC__ < 2) *\/ */

/* #if !defined(HAVE_ATTRIBUTE__NONNULL__) && !defined(__nonnull__) */
/* # define __nonnull__(x) */
/* #endif */

#define __attribute__(x)
#define __nonnull__(x)

#ifndef MAP_LOCKED
#  define MAP_LOCKED 0
#endif

#if !defined(MAP_ANONYMOUS) && defined(MAP_ANON)
#  define MAP_ANONYMOUS MAP_ANON
#endif

/* OpenBSD function replacements */
#include "keys/base64.h"
#include "keys/sha2.h"
#include "keys/blf.h"
#include "keys/readpassphrase.h"

#ifndef HAVE_BCRYPT_PBKDF
int	bcrypt_pbkdf(const char *, size_t, const u_int8_t *, size_t,
    u_int8_t *, size_t, unsigned int);
#endif

#ifndef HAVE_EXPLICIT_BZERO
void explicit_bzero(void *p, size_t n);
#endif

#ifndef HAVE_FREEZERO
void freezero(void *, size_t);
#endif

#ifndef HAVE_TIMINGSAFE_BCMP
int timingsafe_bcmp(const void *, const void *, size_t);
#endif


#include "sqlite3.h" /* looks in the sub-directory with the given version */
#include "crypt4gh.h"
#include "keys/key.h"

struct fs_config {

  uid_t uid;
  gid_t gid;
  char* groupname;
  char* username;
  gid_t supp_gid;
  char* supp_group;

  time_t mounted_at;
  time_t created_at;
  int direct_io;

  int is_readwrite;
  unsigned int dperm; /* Controlled using the umask: 777 & ~umask */
  unsigned int fperm; /* Controlled using the umask: 666 & ~umask */

  int local_debug;
  int verbose;
  int foreground;
  char *progname;
  int show_version;
  int show_help;

  char *mountpoint;
  double entry_timeout; /* in seconds, for which name lookups will be cached */
  double attr_timeout; /* in seconds for which file/directory attributes are cached */


  pid_t pid; // used for st_dev

  unsigned int dir_cache;
  unsigned int file_cache;

  /* if Crypt4GH is enabled */
  char* seckeypath;
  char* passphrase;
  char* passphrase_from_env;
  uint8_t seckey[crypto_kx_SECRETKEYBYTES]; /* unlocked secret key. TODO: better protect it */
  uint8_t pubkey[crypto_kx_PUBLICKEYBYTES];

  /* SQLite database */
  char* db_path;
  sqlite3* db;
  
  /* multithreaded */
  int singlethread;
  int clone_fd;
  unsigned int max_threads;
};


extern struct fs_config config;
struct fuse_lowlevel_ops* fs_operations(void);

/* DEBUG output */
#ifdef NO_DEBUG
#define D1_(fmt, ...)
#define D2_(fmt, ...)
#define D3_(fmt, ...)
#else
#define D1_(fmt, ...) if(config.local_debug > 0) fprintf(stderr, "# " fmt, ##__VA_ARGS__)
#define D2_(fmt, ...) if(config.local_debug > 1) fprintf(stderr, "#      " fmt, ##__VA_ARGS__)
#define D3_(fmt, ...) if(config.local_debug > 2) fprintf(stderr, "#           " fmt, ##__VA_ARGS__)
#endif

#define D1(fmt, ...) D1_(fmt "\n", ##__VA_ARGS__)
#define D2(fmt, ...) D2_(fmt "\n", ##__VA_ARGS__)
#define D3(fmt, ...) D3_(fmt "\n", ##__VA_ARGS__)
#define E(fmt, ...)  fprintf(stderr, "\x1b[31mError:\x1b[0m " fmt "\n", ##__VA_ARGS__)
#define W(fmt, ...)  fprintf(stderr, "Warning: " fmt "\n", ##__VA_ARGS__)
