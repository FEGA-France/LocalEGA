#include <sys/types.h> 
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <unistd.h>
#include <nss.h>
#include <pwd.h>
#include <shadow.h>
#include <grp.h>
#include <errno.h>
#include <sys/mman.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#include <limits.h>


#ifndef EGAFILES_USERS_PATH
#define EGAFILES_USERS_PATH "/etc/ega/cache/nss/users"
#endif

#ifndef EGAFILES_GROUPS_PATH
#define EGAFILES_GROUPS_PATH "/etc/ega/cache/nss/groups"
#endif

#ifndef EGAFILES_PASSWORDS_PATH
#define EGAFILES_PASSWORDS_PATH "/etc/ega/cache/nss/passwords"
#endif


#define E(...)
#define D1(...)
#define D2(...)
#define D3(...)

#ifdef DEBUG

#define DEBUG_FUNC(level, fmt, ...) fprintf(stderr, "[%5d / %5d] %-10s(%3d)%22s |" level " " fmt "\n", getppid(), getpid(), __FILE__, __LINE__, __FUNCTION__, ##__VA_ARGS__)
#define LEVEL1 ""
#define LEVEL2 "    "
#define LEVEL3 "        "

#if DEBUG > 0
#undef D1
#undef E
#define D1(fmt, ...) DEBUG_FUNC(LEVEL1, fmt, ##__VA_ARGS__)
#define E(fmt, ...) DEBUG_FUNC("ERROR:", fmt, ##__VA_ARGS__)
#endif

#if DEBUG > 1
#undef D2
#define D2(fmt, ...) DEBUG_FUNC(LEVEL2, fmt, ##__VA_ARGS__)
#endif

#if DEBUG > 2
#undef D3
#define D3(fmt, ...) DEBUG_FUNC(LEVEL3, fmt, ##__VA_ARGS__)
#endif

#endif /* !DEBUG */

/* Users: 'passwd' database in NSS parlour */
static char p_path[PATH_MAX] = EGAFILES_USERS_PATH;
static FILE *p_file = NULL;
static pthread_mutex_t p_mutex = PTHREAD_MUTEX_INITIALIZER;
#define NSS_EGAFILES_P_LOCK()   pthread_mutex_lock(&p_mutex)
#define NSS_EGAFILES_P_UNLOCK() pthread_mutex_unlock(&p_mutex)

/* Passwords: 'shadow' database in NSS parlour */
static char s_path[PATH_MAX] = EGAFILES_PASSWORDS_PATH;
static FILE *s_file = NULL;
static pthread_mutex_t s_mutex = PTHREAD_MUTEX_INITIALIZER;
#define NSS_EGAFILES_S_LOCK()   pthread_mutex_lock(&s_mutex)
#define NSS_EGAFILES_S_UNLOCK() pthread_mutex_unlock(&s_mutex)

/* Groups: 'group' database in NSS parlour */
static char g_path[PATH_MAX] = EGAFILES_GROUPS_PATH;
static FILE *g_file = NULL;
static pthread_mutex_t g_mutex = PTHREAD_MUTEX_INITIALIZER;
#define NSS_EGAFILES_G_LOCK()   pthread_mutex_lock(&g_mutex)
#define NSS_EGAFILES_G_UNLOCK() pthread_mutex_unlock(&g_mutex)


/*
 * Constructor/Destructor when the library is loaded
 *
 * See: http://man7.org/linux/man-pages/man3/dlopen.3.html
 *
 */
__attribute__((destructor))
static void
destroy(void)
{
  NSS_EGAFILES_P_LOCK();
  if (p_file) {
    D3("Unloading the library: Closing users file: %s (fd: %d)\n", p_path, fileno(p_file));
    fclose(p_file);
    p_file = NULL;
  }
  NSS_EGAFILES_P_UNLOCK();

  NSS_EGAFILES_S_LOCK();
  if (s_file) {
    D3("Unloading the library: Closing passwords file: %s (fd: %d)\n", s_path, fileno(s_file));
    fclose(s_file);
    s_file = NULL;
  }
  NSS_EGAFILES_S_UNLOCK();

  NSS_EGAFILES_G_LOCK();
  if (g_file) {
    D3("Unloading the library: Closing groups file: %s (fd: %d)\n", g_path, fileno(g_file));
    fclose(g_file);
    g_file = NULL;
  }
  NSS_EGAFILES_G_UNLOCK();
}


/*
 * ===========================================================
 *
 *   Users functions
 *
 * ===========================================================
 */

static enum nss_status
_nss_egafiles_setpwent_locked(void)
{
  D3("Opening users: %s", p_path);
  p_file = fopen(p_path, "r");
  D3("=> fd: %d", (p_file)?fileno(p_file):-1);
  return (p_file) ? NSS_STATUS_SUCCESS: NSS_STATUS_UNAVAIL;
}

static enum nss_status
_nss_egafiles_endpwent_locked(void)
{
  if (p_file) {
    D3("Closing users: %s (fd: %d)", p_path, fileno(p_file));
    fclose(p_file);
    p_file = NULL;
  }
  return NSS_STATUS_SUCCESS;
}

/* 'stayopen' parameter is ignored. */
enum nss_status
_nss_egafiles_setpwent(int stayopen)
{
  enum nss_status ret;
  NSS_EGAFILES_P_LOCK();
  ret = _nss_egafiles_setpwent_locked();
  NSS_EGAFILES_P_UNLOCK();
  return ret;
}

enum nss_status
_nss_egafiles_endpwent(void) {
  enum nss_status ret;
  NSS_EGAFILES_P_LOCK();
  ret = _nss_egafiles_endpwent_locked();
  NSS_EGAFILES_P_UNLOCK();
  return ret;
}

static enum nss_status
_nss_egafiles_getpwent_r_locked(struct passwd *result,
			    char *buffer, size_t buflen,
			    int *errnop) {

  if (p_file == NULL) {
    D3("p_file == NULL, opening it");
    enum nss_status ret = _nss_egafiles_setpwent_locked();
    if(ret != NSS_STATUS_SUCCESS)
      return ret;
  }

  fpos_t position;
  fgetpos(p_file, &position);

  if (fgetpwent_r(p_file, result, buffer, buflen, &result) == 0) {
    D3("Lookup user %s [id: %d]", result->pw_name, result->pw_uid);
    return NSS_STATUS_SUCCESS;
  }

  /* error: rewind */
  fsetpos(p_file, &position);

  D3("error: %s", strerror(errno));

  if(errno == ERANGE){
    D2("ERANGE: Try again with a bigger buffer");
    return NSS_STATUS_TRYAGAIN;
  }

  if (errno == ENOENT)
    errno = 0;
  
  if(errno)
    *errnop = errno;
  return NSS_STATUS_NOTFOUND;
}


enum nss_status
_nss_egafiles_getpwent_r(struct passwd *result, char *buffer, size_t buflen, int *errnop){
  enum nss_status ret;
  NSS_EGAFILES_P_LOCK();
  ret = _nss_egafiles_getpwent_r_locked(result, buffer, buflen, errnop);
  NSS_EGAFILES_P_UNLOCK();
  return ret;
}

enum nss_status
_nss_egafiles_getpwuid_r(uid_t uid, struct passwd *result,
		    char *buffer, size_t buflen, int *errnop)
{
  /* bail out if we're looking for the root user or a negative user */
  
  if( uid == 0 ){ D1("bail out when root"); *errnop = ENOENT; return NSS_STATUS_NOTFOUND; }

  D1("Looking up user id %u", uid);
  if( uid < 0 ){ D2("... too low: ignoring"); *errnop = ENOENT; return NSS_STATUS_NOTFOUND; }

  NSS_EGAFILES_P_LOCK();
  
  /* Linear search.
   *
   * Tips for later: make a sorted version of the file, and implement a binary search
   */ 
  enum nss_status ret = _nss_egafiles_setpwent_locked();

  while ((ret = _nss_egafiles_getpwent_r_locked(result, buffer, buflen, errnop)) == NSS_STATUS_SUCCESS) {
    if (result->pw_uid == uid) break;
  }
  
  (void)_nss_egafiles_endpwent_locked(); /* ignore result */
  NSS_EGAFILES_P_UNLOCK();

  return ret;
}

/* Find user ny name */
enum nss_status
_nss_egafiles_getpwnam_r(const char *username, struct passwd *result,
		    char *buffer, size_t buflen, int *errnop)
{
  /* bail out if we're looking for the root user */
  if( !strcmp(username, "root") ){ D1("bail out when root"); return NSS_STATUS_NOTFOUND; }

  NSS_EGAFILES_P_LOCK();

  /* Linear search.
   *
   * Tips for later: make a sorted version of the file, and implement a binary search
   */ 
  enum nss_status ret = _nss_egafiles_setpwent_locked();

  if(ret != NSS_STATUS_SUCCESS){ /* eg couldn't open the file */
    NSS_EGAFILES_P_UNLOCK();
    return ret;
  }

  while ((ret = _nss_egafiles_getpwent_r_locked(result, buffer, buflen, errnop)) == NSS_STATUS_SUCCESS) {
    if (!strcmp(result->pw_name, username)) break;
  }
  
  (void)_nss_egafiles_endpwent_locked(); /* ignore result */
  NSS_EGAFILES_P_UNLOCK();

  return ret;
}


/* 
 * ===========================================================
 *
 *   Shadow Entry functions
 *
 * =========================================================== 
 */

static enum nss_status
_nss_egafiles_setspent_locked(void)
{
  D3("Opening users: %s", s_path);
  s_file = fopen(s_path, "r");
  D3("=> fd: %d", (s_file)?fileno(s_file):-1);
  return (s_file) ? NSS_STATUS_SUCCESS: NSS_STATUS_UNAVAIL;
}

static enum nss_status
_nss_egafiles_endspent_locked(void)
{
  if (s_file) {
    D3("Closing passwords: %s (fd: %d)", s_path, fileno(s_file));
    fclose(s_file);
    s_file = NULL;
  }
  return NSS_STATUS_SUCCESS;
}

/* 'stayopen' parameter is ignored. */
enum nss_status
_nss_egafiles_setspent(int stayopen)
{
  enum nss_status ret;
  NSS_EGAFILES_S_LOCK();
  ret = _nss_egafiles_setspent_locked();
  NSS_EGAFILES_S_UNLOCK();
  return ret;
}

enum nss_status
_nss_egafiles_endspent(void) {
  enum nss_status ret;
  NSS_EGAFILES_S_LOCK();
  ret = _nss_egafiles_endspent_locked();
  NSS_EGAFILES_S_UNLOCK();
  return ret;
}

static enum nss_status
_nss_egafiles_getspent_r_locked(struct spwd *result,
			    char *buffer, size_t buflen,
			    int *errnop) {
  
  if (s_file == NULL) {
    D3("s_file == NULL, opening it");
    enum nss_status ret = _nss_egafiles_setspent(1); /* stayopen: ignored */
    if(ret != NSS_STATUS_SUCCESS)
      return ret;
  }

  fpos_t position;
  fgetpos(s_file, &position);

  if (fgetspent_r(s_file, result, buffer, buflen, &result) == 0) {
    D3("Lookup user %s", result->sp_namp);
    D3("=> password: %s", result->sp_pwdp);
    return NSS_STATUS_SUCCESS;
  }

  /* error: rewind */
  fsetpos(s_file, &position);

  if(errno == ERANGE){
    D2("ERANGE: Try again with a bigger buffer");
    return NSS_STATUS_TRYAGAIN;
  }

  if (errno == ENOENT)
    errno = 0;
  
  if(errno)
    *errnop = errno;
  return NSS_STATUS_NOTFOUND;
}


enum nss_status
_nss_egafiles_getspent_r(struct spwd *result, char *buffer, size_t buflen, int *errnop){
  enum nss_status ret;
  NSS_EGAFILES_S_LOCK();
  ret = _nss_egafiles_getspent_r_locked(result, buffer, buflen, errnop);
  NSS_EGAFILES_S_UNLOCK();
  return ret;
}

enum nss_status
_nss_egafiles_getspnam_r(const char *username, struct spwd *result,
		     char *buffer, size_t buflen, int *errnop)
{
  /* bail out if we're looking for the root user */
  if( !strcmp(username, "root") ){ D1("bail out when root"); return NSS_STATUS_NOTFOUND; }

  /* if( getuid() != 0 ){ return NSS_STATUS_NOTFOUND; } */
  /* D3("Ok, you are root, go go gadget \"fetch password hashes\""); */

  NSS_EGAFILES_S_LOCK();

  enum nss_status ret = _nss_egafiles_setspent_locked();

  if(ret != NSS_STATUS_SUCCESS){ /* eg couldn't open the file */
    NSS_EGAFILES_S_UNLOCK();
    return ret;
  }

  while ((ret = _nss_egafiles_getspent_r_locked(result, buffer, buflen, errnop)) == NSS_STATUS_SUCCESS) {
    if (!strcmp(result->sp_namp, username)) break;
  }

  (void)_nss_egafiles_endspent_locked();
  NSS_EGAFILES_S_UNLOCK();
  return ret;
}



/* 
 * ===========================================================
 *
 *   Group functions
 *
 * =========================================================== 
 */

static enum nss_status
_nss_egafiles_setgrent_locked(void)
{
  D3("Opening groups: %s", g_path);
  g_file = fopen(g_path, "r");
  D3("=> fd: %d", (g_file)?fileno(g_file):-1);
  return (g_file) ? NSS_STATUS_SUCCESS: NSS_STATUS_UNAVAIL;
}

static enum nss_status
_nss_egafiles_endgrent_locked(void)
{
  if (g_file) {
    D3("Closing groups: %s (fd: %d)", g_path, fileno(g_file));
    fclose(g_file);
    g_file = NULL;
  }
  return NSS_STATUS_SUCCESS;
}

/* 'stayopen' parameter is ignored. */
enum nss_status
_nss_egafiles_setgrent(int stayopen)
{
  enum nss_status ret;
  NSS_EGAFILES_G_LOCK();
  ret = _nss_egafiles_setgrent_locked();
  NSS_EGAFILES_G_UNLOCK();
  return ret;
}

enum nss_status
_nss_egafiles_endgrent(void) {
  enum nss_status ret;
  NSS_EGAFILES_G_LOCK();
  ret = _nss_egafiles_endgrent_locked();
  NSS_EGAFILES_G_UNLOCK();
  return ret;
}

static enum nss_status
_nss_egafiles_getgrent_r_locked(struct group *result,
			    char *buffer, size_t buflen,
			    int *errnop) {

  D3("starting with buffer size %zu", buflen);
  
  if (g_file == NULL) {
    D3("g_file == NULL, opening it");
    enum nss_status ret = _nss_egafiles_setgrent(1); /* stayopen: ignored */
    if(ret != NSS_STATUS_SUCCESS)
      return ret;
  }

  fpos_t position;
  fgetpos(g_file, &position);

  if (fgetgrent_r(g_file, result, buffer, buflen, &result) == 0) {
    D2("Lookup group for %s", result->gr_name);
    return NSS_STATUS_SUCCESS;
  }

  /* error: Rewind back to where we were just before, otherwise the
   * data read into the buffer is probably going to be lost because
   * there's no guarantee that the caller is going to have preserved
   * the line we just read.  Note that glibc's
   * nss/nss_files/files-XXX.c does something similar in
   * CONCAT(_nss_files_get,ENTNAME_r) (around line 242 in glibc 2.4
   * sources).
   */
  fsetpos(g_file, &position);

  if(errno == ERANGE){
    D2("ERANGE: Try again with a bigger buffer");
    return NSS_STATUS_TRYAGAIN;
  }

  if (errno == ENOENT)
    errno = 0;

  if(errno)
    *errnop = errno;
  return NSS_STATUS_NOTFOUND;
}


enum nss_status
_nss_egafiles_getgrent_r(struct group *result, char *buffer, size_t buflen, int *errnop){
  enum nss_status ret;
  NSS_EGAFILES_G_LOCK();
  ret = _nss_egafiles_getgrent_r_locked(result, buffer, buflen, errnop);
  NSS_EGAFILES_G_UNLOCK();
  return ret;
}

enum nss_status
_nss_egafiles_getgrnam_r(const char *groupname, struct group *result,
			 char *buffer, size_t buflen, int *errnop)
{
  /* bail out if we're looking for the root group */
  if( !strcmp(groupname, "root") ){ D1("bail out when root"); return NSS_STATUS_NOTFOUND; }

  NSS_EGAFILES_G_LOCK();

  D2("Searching for group: %s", groupname);

  enum nss_status ret = _nss_egafiles_setgrent_locked();

  if(ret != NSS_STATUS_SUCCESS){ /* eg couldn't open the file */
    NSS_EGAFILES_G_UNLOCK();
    return ret;
  }

  while ((ret = _nss_egafiles_getgrent_r_locked(result, buffer, buflen, errnop)) == NSS_STATUS_SUCCESS) {
    if (!strcmp(result->gr_name, groupname)) break;
  }

  (void)_nss_egafiles_endgrent_locked();
  NSS_EGAFILES_G_UNLOCK();
  return ret;
}

enum nss_status
_nss_egafiles_getgrgid_r(gid_t gid, struct group *result,
			 char *buffer, size_t buflen, int *errnop)
{
  /* bail out if we're looking for the root group */
  if( gid == 0 ){ D1("bail out when root"); return NSS_STATUS_NOTFOUND; }

  NSS_EGAFILES_G_LOCK();

  enum nss_status ret = _nss_egafiles_setgrent_locked();

  if(ret != NSS_STATUS_SUCCESS){ /* eg couldn't open the file */
    NSS_EGAFILES_G_UNLOCK();
    return ret;
  }

  while ((ret = _nss_egafiles_getgrent_r_locked(result, buffer, buflen, errnop)) == NSS_STATUS_SUCCESS) {
    if (result->gr_gid == gid) break;
  }

  (void)_nss_egafiles_endgrent_locked();
  NSS_EGAFILES_G_UNLOCK();
  return ret;
}
