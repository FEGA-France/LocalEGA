#include <sys/types.h>
#include <sys/stat.h> /* for chmod */
#include <stdio.h>
#include <unistd.h>
#include <pwd.h>
#include <limits.h> /* PATH_MAX */
#include <string.h>
#include <errno.h>

#define PAM_SM_ACCT
#include <security/pam_appl.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <security/pam_modutil.h>

#include "utils.h"

#define EGA_OPT_SILENT	          (1)
#define EGA_OPT_DEBUG	          (1 << 1)
#define EGA_BAIL_ON_EXISTS        (1 << 2)

/* The chroot directory needs to be owned by root, and neither group not world-writable.
   So a good old 700 will do it, but then sftp can't go in it as the user.
   So we go with 755
   See:
   - ChrootDirectory parameter for sshd_config
     (eg https://github.com/openssh/openssh-portable/blob/master/sshd_config.5#L398-L401)
   - https://www.halfdog.net/Security/2018/OpensshSftpChrootCodeExecution/
   - https://tech-kern.netbsd.narkive.com/xmOp0t02/chroot-why-super-user-only
*/
#define DEFAULT_CHROOT_ATTRS 0550 /* r-xr-x--- */
#define DEFAULT_SUBDIR_ATTRS 0700 /* rwx------ */
#define DEFAULT_MAX_SUBDIRS  4

struct options_s {
  int flags;
  const char* subdirs[DEFAULT_MAX_SUBDIRS]; /* Directory for safely chrooting */
  int subdir_idx;
  mode_t attrs;
};

PAM_EXTERN int
pam_sm_acct_mgmt(pam_handle_t *pamh, int flags, int argc, const char *argv[])
{
  D1("Account: Create the homedir");
  const char *username;
  int rc, i;
  struct options_s opts;

  D3("Getting account PAM module options");
  /* defaults */
  opts.flags = 0;
  opts.subdir_idx = 0;
  opts.attrs = DEFAULT_SUBDIR_ATTRS;

  /* Step through module arguments */
  for (; argc-- > 0; ++argv){
    if (!strcmp(*argv, "debug")) {
      opts.flags |= EGA_OPT_DEBUG;
    } else if (!strcmp(*argv, "silent")) {
      opts.flags |= EGA_OPT_SILENT;
    } else if (!strncmp(*argv, "subdir=", 7)) {
      if(opts.subdir_idx > DEFAULT_MAX_SUBDIRS){
	D1("Too many subdirs: %d", DEFAULT_MAX_SUBDIRS);
	return PAM_PERM_DENIED;
      }
      opts.subdirs[opts.subdir_idx++] = *argv+7;
    } else if (!strcmp(*argv, "bail_on_exists")) {
      opts.flags |= EGA_BAIL_ON_EXISTS;
    } else if (!strncmp(*argv, "attrs=", 6)) {
      opts.attrs = (mode_t)strtol(*argv+6, NULL, 8);
    } else {
      D1("unknown option: %s", *argv);
      /* pam_syslog(pamh, LOG_ERR, "unknown option: %s", *argv); */
      return PAM_PERM_DENIED;
    }
  }

  D3("options: flags = %d", opts.flags);
  for(i = 0; i < opts.subdir_idx; i++)
    D3("options: subdir = %s", opts.subdirs[i]);
  D3("options: attrs = %o", opts.attrs);


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

  D1("Homedir for %s: %s", user->pw_name, user->pw_dir);
  errno = 0;

  /* Create the home directory - not a recursive call. */
  rc = mkdir(user->pw_dir, DEFAULT_CHROOT_ATTRS); /* with default permissions when creating */
  if (rc && errno != EEXIST) {
    D2("unable to mkdir %s [%o] | rc: %d | %s", user->pw_dir, DEFAULT_CHROOT_ATTRS, rc, strerror(errno));
    return PAM_PERM_DENIED;
  }

  /* we enforce root-ownership, but leave the group owner as-is */
  rc = chown(user->pw_dir, 0, user->pw_gid);
  if(rc){
    D2("unable to change ownership to root | rc: %d | %s", rc, strerror(errno));
    return PAM_PERM_DENIED;
  }
  
  /* we enforce default permissions */
  rc = chmod(user->pw_dir, DEFAULT_CHROOT_ATTRS);
  if (rc){
    D2("unable to change permissions to %o | rc: %d | %s", DEFAULT_CHROOT_ATTRS, rc, strerror(errno));
    return PAM_PERM_DENIED;
  }

  /* we create a subdirectory named by variable "subdir" */
  char subdir[PATH_MAX];
  for(i = 0; i < opts.subdir_idx; i++){
    int subdir_len = strlen(user->pw_dir) + strlen(opts.subdirs[i]) + 2; /* +1 for the slash and the null-terminator */

    D3("subdir %s [attrs: %o]", opts.subdirs[i], opts.attrs);

    if(subdir_len > PATH_MAX || /* too long */
       !snprintf(subdir, subdir_len, "%s/%s", user->pw_dir, opts.subdirs[i])){
      D2("error concat %s to %s: we got %s", user->pw_dir, opts.subdirs[i], subdir);
      return PAM_PERM_DENIED;
    }

    /* Create it with opts.attrs */
    D3("chmod %o %s ", opts.attrs, subdir);
    rc = mkdir(subdir, opts.attrs);
    if(rc && errno != EEXIST){
      D2("unable to sub-mkdir %o %s | rc: %d | %s", opts.attrs, subdir, rc, strerror(errno));
      return PAM_PERM_DENIED;
    }

    if( rc && errno == EEXIST && (opts.flags & EGA_BAIL_ON_EXISTS)){
      D2("%s exists | Assume success", subdir);
      continue;
      //return PAM_SUCCESS;
    }

    /* User-ownership */
    D3("chown %d:%d %s", user->pw_uid, user->pw_gid, subdir);
    rc = chown(subdir, user->pw_uid, user->pw_gid);
    if(rc){
      D2("unable to change ownership to %d:%d | rc: %d | %s", user->pw_uid, user->pw_gid, rc, strerror(errno));
      return PAM_PERM_DENIED;
    }

    /* we enforce default permissions */
    rc = chmod(subdir, DEFAULT_SUBDIR_ATTRS);
    if (rc){
      D2("unable to change permissions of %s to %o | rc: %d | %s", subdir, DEFAULT_SUBDIR_ATTRS, rc, strerror(errno));
      return PAM_PERM_DENIED;
    }
    D1("sub-directory %s created", subdir);
  } 

  return PAM_SUCCESS;
}
