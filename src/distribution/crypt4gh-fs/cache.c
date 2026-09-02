/* #define DEBUG 1 */
/* #include "debug.h" */

#include "includes.h"

#include <glib.h>

/* We are using gpointer store the fuse_ino_t values.
   The following incantation checks this condition at compile time. */
#if defined(__GNUC__) && (__GNUC__ > 4 || __GNUC__ == 4 && __GNUC_MINOR__ >= 6) && !defined __cplusplus
_Static_assert(sizeof(fuse_ino_t) <= sizeof(gpointer),
	       "fuse_ino_t too big to fit in gpointer values!");
#else
struct _fuse_ino_t_must_fit_in_gpointer_dummy_struct \
	{ unsigned _fuse_ino_t_must_fit_in_gpointer: ((sizeof(fuse_ino_t) <= sizeof(gpointer)) ? 1 : -1); };
#endif

/* global variables */
static GHashTable *cache;
static pthread_mutex_t cache_lock;

static void
free_node(gpointer n)
{
  if(n) free((char*)n);
}

void
ega_cache_init(void)
{
  /* For the cache: ino => decrypted_size as str */
  pthread_mutex_init(&cache_lock, NULL);
  cache = g_hash_table_new_full(g_direct_hash, g_direct_equal,
				NULL, free_node);
  if (cache == NULL) {
    E("Allocating cache failed!");
    E("Aborting...");
    exit( EXIT_FAILURE );
  }
}

void
ega_cache_destroy(void)
{
  pthread_mutex_lock(&cache_lock);
  g_hash_table_destroy(cache);
  cache = NULL;
  pthread_mutex_unlock(&cache_lock);
}



char*
ega_cache_get(fuse_ino_t ino)
{
  D2("lookup decrypted size for ino %lu", ino);
  char* res;
  pthread_mutex_lock(&cache_lock);
  res = (char*) g_hash_table_lookup(cache, GUINT_TO_POINTER(ino));
  pthread_mutex_unlock(&cache_lock);
  D2("ino %lu => %s", ino, (res)?res:"[not found]");
  return res;
}

void
ega_cache_put(fuse_ino_t ino, const char* value)
{
  D2("inserting decrypted size for ino %lu: %s", ino, value);
  pthread_mutex_lock(&cache_lock);
  char* copy = g_strdup(value);
  if(copy)
    g_hash_table_replace(cache, GUINT_TO_POINTER(ino), copy);
  else
    E("Memory allocation failed for copy of %s", value);
  pthread_mutex_unlock(&cache_lock);
}
