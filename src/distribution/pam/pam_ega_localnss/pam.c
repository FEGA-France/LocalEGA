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
/* #include <sys/mount.h> */

#define PAM_SM_ACCT
#include <security/pam_appl.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <security/pam_modutil.h>

#include "utils.h"

/* ------ Notes ------

   - we add a group entry in the /etc/group file for 
          "<service-name>:x:<service-gid>"
     so that it prints nicely when the sftp client issues a "ls -al"

   - root is displayed as "ega"

   - we let the setgid do its thing when creating the user home directory,
     but we make the /etc/{passwd,group} owned by root.
*/

#define EGA_OPT_SILENT	          (1)
#define EGA_OPT_DEBUG	          (1 << 1)

struct options_s {
  int flags;

  const char* group;   /* The (original) system group to include */
  const char* display; /* The (fake) system group to display */
  gid_t gid;           /* Matching group ids */
};


static int ega_create_local_nss(struct passwd* user, struct options_s *opts);
static int pam_options(struct options_s *opts, int argc, const char **argv);

PAM_EXTERN int
pam_sm_acct_mgmt(pam_handle_t *pamh, int flags, int argc, const char *argv[])
{
  D1("Account: Create local NSS files");
  const char *username;
  int rc;

  struct options_s opts;

  D3("Getting open session PAM module options");
  rc = pam_options(&opts, argc, argv);
  if (rc){
    D1("Invalid options");
    return PAM_PERM_DENIED;
  }

  /* Determine the user name so we can get the home directory */
  rc = pam_get_user(pamh, &username, NULL);
  if (rc != PAM_SUCCESS || username == NULL || *username == '\0') {
    D1("Cannot obtain the user name: %s", pam_strerror(pamh, rc));
    return PAM_USER_UNKNOWN;
  }

  /* Fetch home directory passwd entry (using NSS) */
  D3("Looking for %s", username);
  /* struct passwd* user = getpwnam(username); */
  struct passwd* user = pam_modutil_getpwnam(pamh, username);
  if( user == NULL ){ D1("EGA: Unknown user: %s", username); return PAM_ACCT_EXPIRED; }

  return (ega_create_local_nss(user, &opts))? PAM_PERM_DENIED : PAM_SUCCESS;
}


/*
  return:
  -    1   : PAM_PERM_DENIED
  -    0   : PAM_SUCCESS
*/

#define ETC_ATTRS 0755 /* rwxr-xr-x */

static int
ega_create_local_nss(struct passwd* user, struct options_s *opts){

  D1("Inject local NSS for %s", user->pw_name);

  int rc = 1;
  int homedir_len = strlen(user->pw_dir);
  FILE* f = NULL;

  /* create the etc dir */
  D2("creating: %s/etc", user->pw_dir);
  char path[PATH_MAX];
  int path_len = homedir_len + 5; /* homedir + /etc + '\0' */

  if(
     (path_len > PATH_MAX) || /* too long */
     (!snprintf(path, path_len, "%s/etc", user->pw_dir)) ||
     /* create dir */
     (mkdir(path, ETC_ATTRS) && errno != EEXIST) ||
     (chown(path, 0, 0)) || /* make it owned by root */
     (chmod(path, ETC_ATTRS)) /* enforce */
     ){
    D2("error with /etc dir: %s", strerror(errno));
    rc = 1;
    goto bailout;
  }

  D3("%s created", path);

  /* create the passwd file */
  mode_t m = S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH; /* rw- r-- r-- */

  D3("creating passwd file");
  path_len = homedir_len + 12; /* homedir + /etc/passwd + '\0' */

  if(
     (path_len > PATH_MAX) || /* too long */
     (!snprintf(path, path_len, "%s/etc/passwd", user->pw_dir)) ||
     /* make it writable, unless not existing */
     (chmod(path, 0600) && errno != ENOENT) ||
     /* open in write mode, and (re)create the file */
     ((f = fopen(path, "w")) == NULL) || 
     /* root:x:0:0:::/sbin/nologin */
     (fprintf(f, "ega:x:0:0:::/bin/false\n") < 0) ||
     /* (fprintf(f, "root:x:0:0:::/bin/false\n") < 0) || */
     /* username:x:uid:gid:gecos:homedir:shell */
     (fprintf(f,
	      "%s:x:%d:%d:%s:%s:%s\n",
	      user->pw_name,
	      user->pw_uid,
	      user->pw_gid,
	      user->pw_gecos,
	      user->pw_dir,
	      user->pw_shell) < 0) ||
     /* close */
     (fclose(f)) ||
     (f = NULL) ||
     /* owned by root */
     (chown(path, 0, 0)) || 
     /* force mode */
     (chmod(path, m))
     ){
    D1("Error reading/creating /etc/passwd: we got %s", path);
    D2("Error %d: %s", errno, strerror(errno));
    rc = 1;
    goto bailout;
  }

  D3("creating passwd file: %s - done", path);
  
  /* create the group file */
  D3("creating group file (with groupname: %s converted from %s [gid: %u])", opts->display, opts->group, opts->gid);
  path_len = homedir_len + 11 ; /* homedir + /etc/group + '\0' */
  memset(path, 0, PATH_MAX);

  if( (path_len <= PATH_MAX /* too long */
       && !snprintf(path, path_len, "%s/etc/group", user->pw_dir)) ||
      /* make it writable, unless not existing */
      (chmod(path, 0600) && errno != ENOENT) ||
      /* open in write mode, and (re)create the file */
      ((f = fopen(path, "w")) == NULL) || 
      /* root:x:0:root */
      (fprintf(f, "ega:x:0:ega\n") < 0) ||
      /* users:x:gid:silverdaz */
      (fprintf(f,
	       "users:x:%d:%s\n",
	       user->pw_gid,
	       user->pw_name) < 0) ||
      /* group:x:gid:members */
      (fprintf(f,
	       "%s:x:%d:%s\n",
	       opts->display,
	       opts->gid,
	       user->pw_name) < 0) ||
      /* close */
      (fclose(f)) ||
      (f = NULL) ||
      /* owned by root */
      (chown(path, 0, 0)) ||
      /* force mode */
      (chmod(path, m))
      ){
    D1("Error reading/creating /etc/group: we got %s", path);
    D2("Error %d: %s", errno, strerror(errno));
    rc = 1;
    goto bailout;
  }

  /* /etc back to rwx r-x r-x */
  if(
     (!snprintf(path, homedir_len + 5, "%s/etc", user->pw_dir)) ||
     chmod(path, ETC_ATTRS)
     ){
    D2("error /etc back to 500");
    rc = 1;
    goto bailout;
  }

  D1("NSS env prepared");
  rc = 0;

bailout:
  if(f != NULL) fclose(f);

  if(rc == 0){ D2("passwd/group files created"); } else { D2("Permission denied"); }
  return rc;
}


static int
pam_options(struct options_s *opts, int argc, const char **argv)
{

  /* defaults */
  opts->flags = 0;
  opts->group = NULL;
  opts->display = NULL;
  //opts->gid = -1;

  /* Step through module arguments */
  for (; argc-- > 0; ++argv){
    if (!strcmp(*argv, "debug")) {
      opts->flags |= EGA_OPT_DEBUG;
    } else if (!strcmp(*argv, "silent")) {
      opts->flags |= EGA_OPT_SILENT;
    } else if (!strncmp(*argv, "group=",6)) {
      struct group *g = getgrnam(*argv+6);
      if(g == NULL){
	D1("unknown group: %s", *argv+6);
	continue;
      }
      opts->gid = g->gr_gid;
      opts->group = *argv+6;
    } else if (!strncmp(*argv, "display=",8)) {
      opts->display = *argv+8;
    } else {
      D1("unknown option: %s", *argv);
      /* pam_syslog(pamh, LOG_ERR, "unknown option: %s", *argv); */
    }
  }

#ifdef DEBUG
  D1("options: flags = %d", opts->flags);
  D1("options: group = %s", opts->group);
  D1("options: display = %s", opts->display);
  D1("options: group id = %u", opts->gid);
#endif

  if(!opts->group || !opts->display)
    return 1; /* bailout */
  return 0;
}
