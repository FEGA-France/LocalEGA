#ifndef __EGA_DIST_DEFS_INCLUDED__
#define __EGA_DIST_DEFS_INCLUDED__ 1

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#define _GNU_SOURCE

#include <sys/types.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <pthread.h>
#include <sys/stat.h>
#include <limits.h>
#include <stdlib.h>

#define FUSE_USE_VERSION 34
#include <fuse3/fuse_lowlevel.h>

#include <libpq-fe.h>

/* for ntohl/htonl */
#include <netinet/in.h>
#include <arpa/inet.h>

/* #if !defined(__GNUC__) || (__GNUC__ < 2) */
/* # define __attribute__(x) */
/* #endif */

#if !defined(HAVE_ATTRIBUTE__NONNULL__) && !defined(__nonnull__)
# define __nonnull__(x)
#endif

#ifdef NO_ATTRIBUTE_ON_PROTOTYPE_ARGS
# define __attribute__(x)
#endif

/* Function replacement / compatibility hacks */
#if !defined(HAVE___func__) && defined(HAVE___FUNCTION__)
#  define __func__ __FUNCTION__
#elif !defined(HAVE___func__)
#  define __func__ ""
#endif

#include "log.h"
#include "readconf.h"
#include "cache.h"
#include "db.h"
#include "pool.h"
#include "fs.h"

#endif /* ! __EGA_DIST_DEFS_INCLUDED__ */
