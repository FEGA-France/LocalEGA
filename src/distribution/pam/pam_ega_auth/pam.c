#include <sys/types.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <shadow.h>

#define PAM_SM_AUTH
#include <security/pam_appl.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <security/pam_modutil.h>

/* #define _OW_SOURCE */
//#include "blowfish/ow-crypt.h"
#include "blowfish/crypt_blowfish.h"

#include "utils.h"

#define EGA_DEFAULT_PROMPT   "Please, enter your EGA password: "

#define EGA_OPT_SILENT	          (1)
#define EGA_OPT_DEBUG	          (1 << 1)
#define EGA_OPT_USE_FIRST_PASS	  (1 << 2)
#define	EGA_OPT_TRY_FIRST_PASS	  (1 << 3)

struct options_s {
  int flags;
  const char* prompt;
};

static void pam_auth_options(struct options_s *opts, int argc, const char **argv);
static int timingsafe_bcmp(const void *b1, const void *b2, size_t n);

/*
 * authenticate user
 */
PAM_EXTERN int
pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv)
{
  const char *user = NULL, *password = NULL;
  const void *item;
  int rc;
  struct options_s opts;
  char* pwdh;
  struct pam_conv *conv = NULL;
  struct pam_message msg;
  const struct pam_message * messages[1]; /* array of one pointer to a message */
  struct pam_response* responses[1]; /* array of one pointer to a response */
  
  D2("Getting auth PAM module options");

  if ((rc = pam_get_user(pamh, &user, NULL)) != PAM_SUCCESS) {
    D1("Can't get user: %s", pam_strerror(pamh, rc));
    goto bailout;
  }
  
  rc = pam_get_item(pamh, PAM_RHOST, &item);
  if ( rc != PAM_SUCCESS) { 
    D1("EGA: Unknown rhost: %s", pam_strerror(pamh, rc));
  }

  D1("Authenticating %s%s%s", user, (item)?" from ":"", (item)?((char*)item):"");

  pam_auth_options(&opts, argc, argv);
  
  /* Grab the already-entered password if we might want to use it. */
  if (opts.flags & (EGA_OPT_TRY_FIRST_PASS | EGA_OPT_USE_FIRST_PASS)){
    rc = pam_get_item(pamh, PAM_AUTHTOK, (const void **)&password);
    if(rc != PAM_SUCCESS){
      D1("(already-entered) password retrieval failed: %s", pam_strerror(pamh, rc));
      goto bailout;
    }
  }

  /* The user hasn't entered a password yet. */
  if (!password && (opts.flags & EGA_OPT_USE_FIRST_PASS)){
    D1("Password retrieval failed: %s", pam_strerror(pamh, rc));
    rc = PAM_AUTH_ERR;
    goto bailout;
  }


  D1("Asking %s for password", user);
  /* Ask for password - don't print it */
  msg.msg_style = PAM_PROMPT_ECHO_OFF;
  msg.msg = opts.prompt;
  messages[0] = &msg;

  rc = pam_get_item(pamh, PAM_CONV, (const void **)&conv);
  if (rc != PAM_SUCCESS){ D1("Conversation initialization failed: %s", pam_strerror(pamh, rc)); goto bailout; }

  /* See: http://www.linux-pam.org/Linux-PAM-html/mwg-expected-by-module-item.html#mwg-pam_conv */
  rc = (conv->conv)(1, messages, (struct pam_response **)responses, conv->appdata_ptr);
  if ( responses == NULL || rc != PAM_SUCCESS ){ D1("Password conversation failed: %s", pam_strerror(pamh, rc)); goto bailout; }

  password = responses[0]->resp;

  /* Check if empty password are disallowed */
  if ((!password || !*password) && (flags & PAM_DISALLOW_NULL_AUTHTOK)) {
    D1("Empty passwords not allowed");
    rc = PAM_AUTH_ERR;
    goto bailout;
  }
  
  /* Now, we have the password */
  D1("Authenticating user %s with password", user);

  struct spwd* spwd = getspnam(user);

  if(spwd == NULL ||
     (pwdh = spwd->sp_pwdp) == NULL){
    D1("Could not load the password hash of '%s'", user);
    rc = PAM_AUTH_ERR;
    goto bailout;
  }


  size_t phlen = (spwd->sp_pwdp == NULL)?0:strlen(spwd->sp_pwdp);

  if(!strncmp(spwd->sp_pwdp, "$2", 2)){
    D2("Using Blowfish");
    char pwdh_computed[64];
    memset(pwdh_computed, '\0', 64);

    if(_crypt_blowfish_rn(password, spwd->sp_pwdp, pwdh_computed, 64) == NULL){
      D2("bcrypt failed: %s", strerror(errno));
      rc = PAM_AUTH_ERR;
      goto bailout;
    }

    //if(!strcmp(password_hash, (char*)pwdh_computed)) { return PAM_SUCCESS; }
    if(phlen == strlen(pwdh_computed) &&
       !timingsafe_bcmp(spwd->sp_pwdp, (char*)pwdh_computed, phlen)) {
      rc = PAM_SUCCESS;
      goto bailout;
    }

  } else {
    D2("Using libc: supporting MD5, SHA256, SHA512");
    char *pwdh_computed = crypt(password, spwd->sp_pwdp);
    if(phlen == strlen(pwdh_computed) &&
       !timingsafe_bcmp(spwd->sp_pwdp, pwdh_computed, phlen)) { 
      rc = PAM_SUCCESS;
      goto bailout;
    }
  }

  D1("Authentication failed for %s", user);
  rc = PAM_AUTH_ERR;

 bailout:
  /* Cleaning the message */
  if( responses[0] != NULL ){
    free(responses[0]->resp);
    free(responses[0]);
  }
  return rc;
}


PAM_EXTERN int
pam_sm_setcred(pam_handle_t *pamh, int flags, int argc, const char **argv)
{
  /* D1("Set cred allowed"); */
  return PAM_SUCCESS;
}

static void
pam_auth_options(struct options_s *opts, int argc, const char **argv)
{

  /* defaults */
  opts->flags = 0;
  opts->prompt = EGA_DEFAULT_PROMPT;

  /* Step through module arguments */
  for (; argc-- > 0; ++argv){
    if (!strcmp(*argv, "debug")) {
      opts->flags |= EGA_OPT_DEBUG;
    } else if (!strcmp(*argv, "silent")) {
      opts->flags |= EGA_OPT_SILENT;
    } else if (!strcmp(*argv, "use_first_pass")) {
      opts->flags |= EGA_OPT_USE_FIRST_PASS;
    } else if (!strcmp(*argv, "try_first_pass")) {
      opts->flags |= EGA_OPT_TRY_FIRST_PASS;
    } else if (!strncmp(*argv, "prompt=", 7)) {
      opts->prompt = *argv+7;
    } else {
      D1("unknown option: %s", *argv);
      /* pam_syslog(pamh, LOG_ERR, "unknown option: %s", *argv); */
    }
  }

#ifdef DEBUG
  D1("options: flags = %d", opts->flags);
  D1("options: prompt = %s", opts->prompt);
#endif

}

static int
timingsafe_bcmp(const void *b1, const void *b2, size_t n)
{
  const unsigned char *p1 = b1, *p2 = b2;
  int ret = 0;

  for (; n > 0; n--)
    ret |= *p1++ ^ *p2++;
  return (ret != 0);
}
