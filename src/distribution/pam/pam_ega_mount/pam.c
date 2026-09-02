
#define _GNU_SOURCE

#include <sys/types.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
#include <pwd.h>
#include <grp.h>
#include <signal.h>
#include <sys/wait.h>
#include <limits.h> /* PATH_MAX and NGROUPS_MAX*/
#include <sys/mount.h> /* for umount */
#include <fcntl.h>

#define PAM_SM_SESSION
#include <security/pam_appl.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <security/pam_modutil.h>

#include "utils.h"

#define EGA_DEFAULT_UMASK    0022      /* Not writable by anyone but the owner */
#define EGA_NGROUPS_MAX      10        /* max 10 supplementary groups */

#define EGA_OPT_SILENT	          (1)
#define EGA_OPT_DEBUG	          (1 << 1)
#define EGA_OPT_UNMOUNTONCLOSE    (1 << 2)
#define EGA_OPT_INIT_GROUPS       (1 << 3)

#define EGA_OPT_MAX_PATTERNS 6

struct options_s {
  int flags;


  char** fuse_argv;
  int fuse_argc;

  const char* lock_pattern;    /* For the lock file */
  const char* mnt_pattern;     /* For the mountpoint */

  const char* fuse_s_patterns[EGA_OPT_MAX_PATTERNS];  /* array of max 4 string pointers that contain %s, replaced by username */
  unsigned int fuse_s_npatterns;

  const char* fuse_conf_name;
  const char* fuse_conf_path;
  int fuse_conf_fd;

  const char* child_notify;

  /* Supplementary groups */
  unsigned int ngroups;
  gid_t groups[EGA_NGROUPS_MAX];

  mode_t umask;
  mode_t unmount_on_close;
};

static int pam_session_options(struct options_s *opts, int argc, const char **argv, int opening);
static int ega_mount_fs(pam_handle_t *pamh, const struct passwd *user, struct options_s* opts);
static int pattern_expand(const char* pattern, const char *username, char** dst);
static int do_lock(const char* lockfile, int *lockfdp, struct flock *lck);
static int do_unlock(const char* lockfile, int lockfd, struct flock *lck);

PAM_EXTERN int
pam_sm_open_session(pam_handle_t *pamh, int flags, int argc, const char **argv)
{
  D1("Open session");
  int rc = PAM_SESSION_ERR;
  struct options_s opts;
  const char *username = NULL;

  D3("Getting open session PAM module options");
  if(pam_session_options(&opts, argc, argv, 1))
    return PAM_SESSION_ERR;

  if (!opts.fuse_conf_path ||
      (opts.fuse_conf_fd = open(opts.fuse_conf_path, O_RDONLY)) == -1){
    D2("Unable to open file: %s", opts.fuse_conf_name);
    return PAM_SESSION_ERR;
  }

  /* Determine the user name so we can get the home directory */
  rc = pam_get_user(pamh, &username, NULL);
  if (rc != PAM_SUCCESS || username == NULL || *username == '\0') {
    D1("Cannot obtain the user name: %s", pam_strerror(pamh, rc));
    rc = PAM_SESSION_ERR;
    goto bailout;
  }

  /* Fetch the user struct using NSS */
  /* struct passwd* user = getpwnam(username); */
  const struct passwd* user = pam_modutil_getpwnam(pamh, username);
  if( user == NULL ){
    D1("EGA: Unknown user: %s", username);
    rc = PAM_SESSION_ERR;
    goto bailout;
  }

  rc = ega_mount_fs(pamh, user, &opts);

bailout:
  if(opts.fuse_conf_fd > 0)
    close(opts.fuse_conf_fd);

  return rc;
}

/*
 * Returning success because we are in the chrooted env
 * so no path to the user's cache entry
 */
PAM_EXTERN int
pam_sm_close_session(pam_handle_t *pamh, int flags, int argc, const char *argv[])
{

  D1("Closing session");
  struct options_s opts;

  D3("Getting close session PAM module options");
  if(pam_session_options(&opts, argc, argv, 0))
    return PAM_SESSION_ERR;

  if( (opts.flags & EGA_OPT_UNMOUNTONCLOSE) == 0 ){
    D1("Closing session: Success | not unmounting");
    return PAM_SUCCESS;
  }

  /*
   * We try to umount the currently running Fuse
   * and ignore the failure, cuz it might be used by another session
   */

  int rc = PAM_SESSION_ERR;
  const char *username = NULL;
  int save_errno = errno;
  int lockfd = -1;
  char *mountpoint = NULL;
  char *lockfile = NULL;

  struct flock lck = {
    .l_whence = SEEK_SET,
    .l_start = 0,
    .l_len = 1,
  };

  /* Determine the user name so we can get the home directory */
  rc = pam_get_user(pamh, &username, NULL);
  if (rc != PAM_SUCCESS || username == NULL || *username == '\0') {
    D1("Cannot obtain the user name: %s", pam_strerror(pamh, rc));
    return PAM_SESSION_ERR;
  }

  /* Expand the mountpoint and lockfile */
  if(pattern_expand(opts.mnt_pattern, username, &mountpoint) /* can't expand */
     //|| mountpoint == NULL /* error */
     //|| strlen(mountpoint) > PATH_MAX /* too long */
     || pattern_expand(opts.lock_pattern, username, &lockfile) /* can't expand */
     //|| lockfile == NULL /* error */
     //|| strlen(lockfile) > PATH_MAX /* too long */
     ){
    rc = PAM_SESSION_ERR;
    goto bailout;
  }

  /* Locking */
  if(do_lock(lockfile, &lockfd, &lck)){
    D1("Error getting a lock on the file description for %s: %s", lockfile, strerror(errno));
    rc = PAM_ABORT;
    goto bailout;
  }

  /* unmount */
  save_errno = errno;
  if(umount(mountpoint))
    D1("not unmounting %s: %s", mountpoint, strerror(errno));
  else
    D1("unmount %s", mountpoint);

  rc = PAM_SUCCESS;

bailout:
  if(lockfd > 0 && do_unlock(lockfile, lockfd, &lck))
    rc = PAM_SESSION_ERR;
  if(mountpoint) free(mountpoint);
  if(lockfile) free(lockfile);
  errno = save_errno;
  D1("Closing session: (%d) %s", rc, (rc == PAM_SUCCESS) ? "Success": "Error");
  return rc;
}

/*
  Return:
  - 0 if true
  - 1 if false
  - 2 on error
*/
static int
is_already_mounted(const char* path)
{
  D1("Checking if %s is already mounted", path);
  struct stat sb;
  struct stat sbp;

  errno = 0;
  if (stat(path, &sb) ||
      !S_ISDIR(sb.st_mode))
    {
      D1("Error on %s: %s", path, strerror(errno));
      return 2;
    }

  char buf[PATH_MAX];
  size_t plen = strlen(path);
  memcpy(buf, path, plen);
  memcpy(buf + plen, "/..", 3);
  buf[plen+3] = '\0';

  D3("Get stats for  %s", buf);
  if (stat(buf, &sbp))
    {
      D1("Error on %s: %s", buf, strerror(errno));
      return 2;
    }

  D3("st_dev compare:  %lu vs %lu", sb.st_dev, sbp.st_dev);
  D3("st_ino compare:  %lu vs %lu", sb.st_ino, sbp.st_ino);

  return (sb.st_dev != sbp.st_dev /* path/.. on a different device as path */
	  || 
	  sb.st_ino == sbp.st_ino /* path/.. is the same i-node as path */
	  )? 0 /* true */ :  1 /* false */ ;
}

static void
run_fuse(pam_handle_t *pamh, const struct passwd *user,
	 unsigned int ngroups, gid_t* groups,
	 const struct options_s* opts,
	 const char* mountpoint, int parent_fd)
{
    errno = 0;

    char** patterns = NULL;
    unsigned int npatterns = 0;
    unsigned int j = 0;
    for(; j<ngroups; j++){
      D3("Supp group[%i]: %u", j, groups[j]);
    }

    /* Drop privileges */
    if (setregid(user->pw_gid, user->pw_gid) || /* Group first */
	setgroups(ngroups, groups) || /* supplementary groups. Dropped if ngroups = 0 */
	setreuid(user->pw_uid, user->pw_uid)
	)
      {
	D1("Error dropping privileges for user %s ", user->pw_name);
	D2("from %d:%d to %d:%d", getuid(), getgid(), user->pw_uid, user->pw_gid);
	D1("errno %d: %s", errno, strerror(errno));
	return;
      }


    /* Detaching the child. See:
     * - http://netzmafia.de/skripten/unix/linux-daemon-howto.html 
     * - https://linux.die.net/man/2/setsid
     */
    D1("Detaching the child process");
    if(setsid() < 0){
      D1("Error detaching the child: %s", strerror(errno));
      return;
    }

    (void) chdir("/");

    /* Redirect the pipes: do not use pam_modutil_sanitize_helper_fds
     * https://github.com/linux-pam/linux-pam/blob/b872b6e68a60ae351ca4c7eea6dfe95cd8f8d130/libpam/pam_modutil_sanitize.c#L115
     * because if closes _all_ file descriptors after stderr, so we can't use the parent_fd for child notification
     */
    D3("Redirecting the pipes");
    int nullfd = open("/dev/null", O_RDWR, 0);
    if (nullfd != -1) {
      (void) dup2(nullfd, 0);
      (void) dup2(nullfd, 1);
      (void) dup2(nullfd, 2);
      if (nullfd > 2)
	close(nullfd);
    } else
      D1("Could not redirect the pipes: %s", strerror(errno));

    /* Setting umask for the child */
    if(opts->umask){
      D3("Setting child umask to 0o%o", opts->umask);
      umask(opts->umask);
    }

    /* expand the other patterns */
    if(opts->fuse_s_npatterns > 0){
      patterns = (char**)malloc(opts->fuse_s_npatterns * sizeof(char*));
      if(!patterns)
	_exit(errno);
      for(j=0; j<opts->fuse_s_npatterns; j++){
	if(pattern_expand(opts->fuse_s_patterns[j], user->pw_name, &patterns[npatterns]) /* can't expand */
	   //|| patterns[npatterns] == NULL /* error */
	   //|| strlen(patterns[npatterns]) > PATH_MAX /* too long */
	   ){
	  D3("FUSE expansion error on pattern %d: %s", j, opts->fuse_s_patterns[j]);
	} else {
	  D3("FUSE pattern %u: %s", npatterns, patterns[npatterns]);
	  npatterns++;
	}
      }
    }

    /* Swapping the child for the FUSE call */
    D3("FUSE mountpoint: %s", mountpoint);
    D3("FUSE euid: %u | egid: %u", geteuid(), getegid());

    if(npatterns != opts->fuse_s_npatterns){ /* clean up */
      for(j=0; j<npatterns; j++){
	if(patterns[j]) free(patterns[j]);
      }
      free(patterns);
      patterns = NULL;
      return;
    }

    /* Convert the conf fd to str */
    char conf_fd_str[100];
    char* conf_name = strdup(opts->fuse_conf_name);
    if(!conf_name) return; /* no mem */
    char *p = strchr(conf_name, ':');
    if(p) *p = '\0';

    if(snprintf(conf_fd_str, 100, "%s=%d", conf_name, opts->fuse_conf_fd) < 9){
      D3("Error passing the conf %s as fd %d", conf_name, opts->fuse_conf_fd);
      free(conf_name);
      _exit(errno);
    }
    free(conf_name);

    char parent_fd_str[100];
    if(parent_fd > 0 && sprintf(parent_fd_str, "%s=%u", opts->child_notify, parent_fd) > 0)
      D3("FUSE waiting for child notification on fd: %d", parent_fd);

    /* Construct the arg list for the execvp */
    const char* argv[opts->fuse_argc + opts->fuse_s_npatterns + 6];
    /* fuse.... -o parent_fd=<N> -o conf_fd=<M> [<pattern>...] <mountpoint> NULL */
    int argc = 0;
    for(; argc<opts->fuse_argc; argc++){
      argv[argc] = opts->fuse_argv[argc];
    }
    argv[argc++] = "-o";
    argv[argc++] = conf_fd_str;
    if( parent_fd > 0 ){
      argv[argc++] = "-o";
      argv[argc++] = parent_fd_str;
    }

    /* include the converted patterns in order */
    if(opts->fuse_s_npatterns > 0){
      for(j=0; j<opts->fuse_s_npatterns; j++){
	argv[argc++] = patterns[j];
      }
    }

    argv[argc++] = mountpoint;
    argv[argc] = NULL; /* important */

#if DEBUG
    int i = 0;
    for(; i<argc; i++){
      D3("FUSE argv[%u]: %s", i, argv[i]);
    }

    struct stat tmpsb;
    if (stat(mountpoint, &tmpsb)){
      D1("Can't stat %s", mountpoint);
    }
    D3("Mountpoint %s owner: %d/%d", mountpoint, tmpsb.st_uid, tmpsb.st_gid);
#endif
    
    execvp(argv[0], (char *const *)argv);
}

/*
 * Mount Fuse FS
 */
static int
ega_mount_fs(pam_handle_t *pamh, const struct passwd *user, struct options_s* opts)
{
  struct sigaction newsa;
  struct sigaction oldsa;
  
  char *mountpoint = NULL;
  char *lockfile = NULL;
  int rc = PAM_ABORT;
  int lockfd = -1;
  int read_fd = -1;
  int write_fd = -1;

  struct flock lck = {
    .l_whence = SEEK_SET,
    .l_start = 0,
    .l_len = 1,
  };

  /* expand the mountpoint and lockfile */
  if(pattern_expand(opts->mnt_pattern, user->pw_name, &mountpoint) /* can't expand */
     //|| mountpoint == NULL /* error */
     //|| strlen(mountpoint) > PATH_MAX /* too long */
     || pattern_expand(opts->lock_pattern, user->pw_name, &lockfile) /* can't expand */
     //|| lockfile == NULL /* error */
     //|| strlen(lockfile) > PATH_MAX /* too long */
     )
    goto bailout; /* PAM _ABORT */
  
  /* Locking */
  if(do_lock(lockfile, &lockfd, &lck)){
    D1("Error getting a lock on the file description for %s: %s", lockfile, strerror(errno));
    rc = PAM_ABORT;
    goto bailout;
  }

  switch(is_already_mounted(mountpoint)){
  case 0:
    D1("Mountpoint already mounted");
    rc = PAM_SUCCESS;
    goto bailout;

  case 2:
    D1("Error checking the mountpoint: %s", strerror(errno));
    rc = PAM_ABORT;
    goto bailout;
  
  default:
    break;
  }

  D1("Mounting Fuse FS for %s into %s", user->pw_name, mountpoint);

  /* Prepare the group list for that user
     Note: https://man7.org/linux/man-pages/man2/setgroups.2.html
     setgroups(0, NULL) drops all supplementary groups
  */
  int ngroups = 0;
  gid_t _groups[NGROUPS_MAX];
  gid_t *groups = NULL;
  if( opts->flags & EGA_OPT_INIT_GROUPS ){
    int ngroups_max = NGROUPS_MAX;
    ngroups = getgrouplist(user->pw_name, user->pw_gid, _groups, &ngroups_max);
    if(ngroups > 0) groups = _groups;
  } else {
    ngroups = opts->ngroups;
    if(ngroups > 0) groups = opts->groups;
  }

  if(ngroups > 0){
    int i = 0;
    for (; i<ngroups; i++){ D2("Adding supplementary group: %d", groups[i]); }
  }

  /*
   * If we are not yet mounted: We fork ourselves and the child is
   * swapped to the FUSE executable We handle signals and file
   * descriptors.  Before executing the child/fuse, we drop privileges
   * to the logged in user.
   *
   * The child might exit quickly, with status 2: It is already mounted
   */
  memset(&newsa, '\0', sizeof(newsa));
  newsa.sa_handler = SIG_DFL;
  sigaction(SIGCHLD, &newsa, &oldsa);

  if( opts->child_notify ){
    int pipefds[2];
    if(pipe(pipefds)){
      D1("pipe() failed: [%d] %s", errno, strerror(errno));
      rc = PAM_ABORT;
      goto signal;
    }
    
    read_fd = pipefds[0];
    write_fd = pipefds[1];
  }

  /* fork */
  errno = 0;
  pid_t child = fork();
  if (child < 0) { D1("EGA-fuse-pam fork failed: %s", strerror(errno)); rc = PAM_ABORT; goto bailout; }

  if (child == 0) { /* This is the child */

    if(read_fd > 0){
      close(read_fd);
      read_fd = -1;
    }
    close(lockfd); /* will inherited lockfd and we close it before execve() does */
    lockfd = -1;
    run_fuse(pamh, user, ngroups, groups, opts, mountpoint, write_fd);

    /* should not get here: exit with error */
    D1("============= Error FUSE exec in %s", mountpoint);
    if(errno){ D1("============= Error: %s", strerror(errno)); }
    if(lockfile) free(lockfile);
    if(mountpoint) free(mountpoint);
    _exit(errno);
  }

  if(write_fd > 0){
    close(write_fd);
    write_fd = -1;
  }

  if( opts->child_notify ){
    char res;
    if(read(read_fd, &res, 1) == 1 && res == '1')
      D1("child is still running: %c", res);
    else
      D1("Child has exited");
  }

  /* The child has not exited: Success */
  if(is_already_mounted(mountpoint) != 0){
    D1("Mountpoint not mounted. Check if the child crashed");
    rc = PAM_SESSION_ERR;
  } else {
    rc = PAM_SUCCESS;
  }

signal:
  sigaction(SIGCHLD, &oldsa, NULL);

bailout:
  if(write_fd > 0)
    close(write_fd);
  if(read_fd > 0)
    close(read_fd);
  if(lockfd > 0 && do_unlock(lockfile, lockfd, &lck))
    rc = PAM_SESSION_ERR;
  if(lockfile) free(lockfile);
  if(mountpoint) free(mountpoint);
  D1("Session open: (%d) %s", rc, (rc == PAM_SUCCESS) ? "Success": "Error");
  return rc;
}

static void
add_supplementary_group(struct options_s *opts, gid_t gid)
{
  D3("Adding %u group as supplementary", gid);
  if(gid == 0){
    D1("root supplementary group forbidden");
    return;
  }
  if(opts->ngroups >= EGA_NGROUPS_MAX){
    D1("Too many supplementary groups");
    return;
  }
  opts->groups[opts->ngroups++] = gid;
}

static int
pam_session_options(struct options_s *opts, int argc, const char **argv, int opening)
{

  /* defaults */
  memset(opts, 0, sizeof(*opts));
  opts->umask = EGA_DEFAULT_UMASK;
  opts->fuse_conf_fd = -1;

  /* Step through module arguments */
  for (; argc-- > 0; ++argv){
    if (!strcmp(*argv, "debug")) {
      opts->flags |= EGA_OPT_DEBUG;
    } else if (!strcmp(*argv, "silent")) {
      opts->flags |= EGA_OPT_SILENT;
    } else if (!strcmp(*argv, "init_groups")) {
      opts->flags |= EGA_OPT_INIT_GROUPS;
    } else if (!strncmp(*argv, "lock=", 5)) {
      opts->lock_pattern = *argv+5;
    } else if (!strncmp(*argv, "supp_group=",11)) {
      if(!opening) continue;
      struct group *g = getgrnam(*argv+11);
      if(g == NULL){
	D1("unknown supplementary group: %s", *argv+11);
	continue;
      }
      add_supplementary_group(opts, g->gr_gid);
    } else if (!strncmp(*argv, "supp_gid=", 9)) {
      if(!opening) continue;
      gid_t gid = (gid_t)strtol(*argv+9, NULL, 10);
      struct group *g = getgrgid(gid);
      if(g == NULL){
	D1("unknown supplementary group: %s", *argv+9);
	//continue;
      } //else
	add_supplementary_group(opts, gid);
    } else if (!strncmp(*argv, "unmount_on_close", 16)) {
        if(opening) continue;
	opts->flags |= EGA_OPT_UNMOUNTONCLOSE;
    } else if (!strncmp(*argv, "child_notify=", 13)) {
        if(!opening) continue;
	opts->child_notify = *argv+13;
    } else if (!strncmp(*argv, "umask=", 6)) {
      if(opening)
	opts->umask = (mode_t)strtol(*argv+6, NULL, 8);
    } else if (!strncmp(*argv, "conf=", 5)) {
      if(!opening) continue;
      char* p = strchr(*argv+5, ':');
      if(!p){
	D1("Invalid conf=name:path | %s", *argv);
	return 1; // error
      }
      opts->fuse_conf_name = *argv+5;
      opts->fuse_conf_path = p+1;
    } else if (!strncmp(*argv, "mnt=", 4)) {
      opts->mnt_pattern = *argv+4;
    } else if (!strncmp(*argv, "pattern=", 8)) {
      if(opts->fuse_s_npatterns > EGA_OPT_MAX_PATTERNS){
	D1("Too many patterns already: %d for %s", opts->fuse_s_npatterns, *argv);
	return 1; // error
      }
      opts->fuse_s_patterns[opts->fuse_s_npatterns++] = *argv+8;
    } else if (!strncmp(*argv, "--", 2)) {
      /* we stop here and save it: this is the fuse command */
      if(argc > 0){
	opts->fuse_argv = (char**)(argv+1);
	opts->fuse_argc = argc; /* already decremented */
      }
      break;
    } else {
      D1("unknown option: %s", *argv);
      /* pam_syslog(pamh, LOG_ERR, "unknown option: %s", *argv); */
    }
  }

  if(!opts->mnt_pattern){
    return 1;
  }

#ifdef DEBUG
  D3("options: flags = %d", opts->flags);
  if(opening){
    D3("options: umask = %o", opts->umask);
    if(opts->ngroups){
      unsigned int i=0;
      D3("options: %d supplementary groups", opts->ngroups);
      for(;i<opts->ngroups;i++){
	D3("options:    -> %d", opts->groups[i]);
      }
    } else {
      D3("No supplementary groups specified");
    }
  }
  if(opts->fuse_argc){
    int i=0;
    for(;i<opts->fuse_argc;i++){
      D3("options: fuse[%d] = %s", i, opts->fuse_argv[i]);
    }
  } else {
      D3("No fuse args");
  }

  if(opts->child_notify)
    D3("options: child notification = %s", opts->child_notify);
  else
    D3("options: no child notification");

  D3("options: lock pattern = %s", opts->lock_pattern);
  D3("options: mnt pattern = %s", opts->mnt_pattern);
  if(opts->fuse_s_npatterns){
    D3("options: fuse string patterns (%u in order)", opts->fuse_s_npatterns);
    unsigned int i=0;
    for(;i<opts->fuse_s_npatterns; i++){
      D3("         * %s", opts->fuse_s_patterns[i]);
    }
  } else {
    D3("options: no fuse string patterns");
  }
#endif

  return 0;
}


static int
pattern_expand(const char* pattern, const char *username, char** dst)
//__attribute__((nonnull))
{
  if(pattern == NULL /* || username == NULL || dst == NULL */){
    D2("nothing to expanding using %s", username);
    return 1;
  }

  if(asprintf(dst, pattern, username) == -1){
    D2("error expanding %s with %s", pattern, username);
    free(*dst);
    *dst = NULL;
    return 2;
  }

  return 0;
}


/*
 * We lock a system-wide open file descript_ion_.
 * Other process will block on it, it the open file description is locked.
 * See:
 *   - https://www.gnu.org/software/libc/manual/html_node/Open-File-Description-Locks.html
 *   - https://www.man7.org/linux/man-pages/man2/fcntl.2.html
 *     (F_OFD_SETLKW is Linux-specific and we need #define _GNU_SOURCE
 */
static int
do_lock(const char* lockfile, int *lockfdp, struct flock *lck)
{
  int lockfd = open(lockfile, O_RDWR | O_CREAT | O_CLOEXEC, 0600);
  if(lockfd == -1){
    D1("Error opening %s: %s", lockfile, strerror(errno));
    return 1;
  }

  D1("========== Locking %s (fd: %d)", lockfile, lockfd);
  lck->l_type = F_WRLCK;
  int rc = fcntl(lockfd, F_OFD_SETLKW, lck);
  if(rc == -1){
    D1("Error getting a lock on the file description for %s: %s", lockfile, strerror(errno));
    return 2;
  }
  
  *lockfdp = lockfd;
  return 0;
}

static int
do_unlock(const char* lockfile, int lockfd, struct flock *lck)
{
  D1("========== Unlocking %s (fd: %d)", lockfile, lockfd);
  lck->l_type = F_UNLCK;
  int rc = fcntl(lockfd, F_OFD_SETLK, lck);
  if(rc == -1){
    D1("Error unlocking (%d): %s", rc, strerror(rc));
    return 1;
  }
  if(remove(lockfile) == -1)
    D3("Error removing %s: %s", lockfile, strerror(errno));
  close(lockfd);
  return 0;
}
