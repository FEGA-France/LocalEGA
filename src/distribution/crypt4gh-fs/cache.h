#ifndef __EGA_DIST_CACHE_INCLUDED__
#define __EGA_DIST_CACHE_INCLUDED__ 1

void ega_cache_init(void);
void ega_cache_destroy(void);
char* ega_cache_get(fuse_ino_t ino);
void ega_cache_put(fuse_ino_t ino, const char* value);

#endif // ! __EGA_DIST_CACHE_INCLUDED__
