/**********************************************************************************
 * Read-only Crypt4GH file system, listing information from an SQLite "database".
 *
 *  Author:  Frédéric Haziza <silverdaz@gmail.com>
 *    Date:  February 2026
 *
 *  This program can be distributed under the terms of the GNU Affero GPL.
 *  See the LICENSE file.
 **********************************************************************************/

#include "includes.h"

#include <sys/capability.h>

#define DEFAULT_MAX_THREADS   10
#define DEFAULT_ENTRY_TIMEOUT 24 * 3600 /* one day */
#define DEFAULT_ATTR_TIMEOUT  24 * 3600 /* one day */
#define MAX_PASSPHRASE        1024
#define MIN(a,b) ((a) < (b))?(a):(b)

/* global variable */
struct fs_config config;

static void usage(struct fuse_args *args)
{
	printf(
"usage: %s <sqlite_filepath> <mountpoint> [options]\n"
"\n"
"    -h   --help            print help\n"
"    -V   --version         print version\n"
"    -f                     foreground operation\n"
"    -s                     disable multi-threaded operation\n"
"    -o opt,[opt...]        mount options\n"
"    -g, --local_debug      print some debugging information (implies -f)\n"
"        --local_debug=N    debug level <N>\n"
"    -o foreground          foreground operation\n"
"    -o direct_io           enable direct i/o\n"
"    -o file_cache          instructs the kernel to cache output data\n"
"    -o dir_cache           instructs the kernel to cache directory listings\n"
"    -o entry_timeout=S     seconds for which lookup names are cached [default: one day]\n"
"    -o attr_timeout=S      seconds for which directories/files attributes are cached [default: one day]\n"
"    -o uid=N               user id of the mount point [default: caller's uid]\n"
"    -o username=S          user name of the mount point [overwrites user_id if exists]\n"
"    -o gid=N               group id of the mount point [default: caller's gid]\n"
"    -o groupname=S         group name of the mount point [overwrites group_id if exists]\n"
"    -o supp_gid=N          supplementary gid (before dropping privileges)\n"
"    -o supp_group=S        supplementary group (before dropping privileges) [overwrites supp_gid if exists]\n"
"\n"
"Crypt4GH Options (if enabled):\n"
"    -o seckey=<path>       Absolute path to the Crypt4GH secret key\n"
"    -o passphrase_from_env=<ENVVAR>\n"
"                           read passphrase from environment variable <ENVVAR>\n"
, args->argv[0]);
}
// TODO: add the undescribed options, like max_threads, and clone_fd


#define CRYPT4GH_SQLITE_OPT(t, p, v) { t, offsetof(struct fs_config, p), v }

static struct fuse_opt fs_opts[] = {

	CRYPT4GH_SQLITE_OPT("-h",		show_help, 1),
	CRYPT4GH_SQLITE_OPT("--help",	show_help, 1),
	CRYPT4GH_SQLITE_OPT("-V",		show_version, 1),
	CRYPT4GH_SQLITE_OPT("--version",	show_version, 1),
	CRYPT4GH_SQLITE_OPT("-v",		verbose, 1),
	CRYPT4GH_SQLITE_OPT("verbose",	verbose, 1),

	CRYPT4GH_SQLITE_OPT("-f",	     foreground, 1),
	CRYPT4GH_SQLITE_OPT("foreground",    foreground, 1),

	CRYPT4GH_SQLITE_OPT("-g",	      local_debug, 1),
	CRYPT4GH_SQLITE_OPT("local_debug",    local_debug, 1),
	CRYPT4GH_SQLITE_OPT("local_debug=%u", local_debug, 0),

	CRYPT4GH_SQLITE_OPT("direct_io",    direct_io, 1),
	CRYPT4GH_SQLITE_OPT("file_cache",   file_cache, 1),
	CRYPT4GH_SQLITE_OPT("dir_cache",   dir_cache, 1),

	/* Mount group id */
	CRYPT4GH_SQLITE_OPT("uid=%u", uid, 0), // chill... it's not root
	CRYPT4GH_SQLITE_OPT("gid=%u", gid, 0),
	CRYPT4GH_SQLITE_OPT("username=%s", username, 0),
	CRYPT4GH_SQLITE_OPT("groupname=%s", groupname, 0),

	CRYPT4GH_SQLITE_OPT("supp_gid=%u", supp_gid, 0),
	CRYPT4GH_SQLITE_OPT("supp_group=%s", supp_group, 0),

	/* in case Crypt4GH is enabled */
	CRYPT4GH_SQLITE_OPT("seckey=%s"             , seckeypath         , 0),
	CRYPT4GH_SQLITE_OPT("passphrase_from_env=%s", passphrase_from_env, 0),

	/* if multithreaded */
	CRYPT4GH_SQLITE_OPT("-s"              , singlethread    , 1),
	CRYPT4GH_SQLITE_OPT("clone_fd"        , clone_fd        , 1),
	CRYPT4GH_SQLITE_OPT("max_threads=%u", max_threads, 0),

	CRYPT4GH_SQLITE_OPT("entry_timeout=%lf",     entry_timeout, 0),
	CRYPT4GH_SQLITE_OPT("attr_timeout=%lf",      attr_timeout, 0),


	/* Ignore these options.
	 * These may come in from /etc/fstab
	 */
	FUSE_OPT_KEY("writeback_cache=no", FUSE_OPT_KEY_DISCARD),
	FUSE_OPT_KEY("auto",               FUSE_OPT_KEY_DISCARD),
	FUSE_OPT_KEY("noauto",             FUSE_OPT_KEY_DISCARD),
	FUSE_OPT_KEY("user",               FUSE_OPT_KEY_DISCARD),
	FUSE_OPT_KEY("nouser",             FUSE_OPT_KEY_DISCARD),
	FUSE_OPT_KEY("users",              FUSE_OPT_KEY_DISCARD),
	FUSE_OPT_KEY("_netdev",            FUSE_OPT_KEY_DISCARD),

	FUSE_OPT_END
};

static int
fs_opt_proc(void *data, const char *arg, int key, struct fuse_args *outargs)
{
	(void) outargs; (void) data;
	char *tmp;

	switch (key) {
	case FUSE_OPT_KEY_OPT:
	  /* Pass through */
	  return 1;

	case FUSE_OPT_KEY_NONOPT:
	  /* first one: SQLite file
	   * second one: mountpoint
	   */
	  if (!config.db_path) {
	    config.db_path = strdup(arg);
	    return 0;
	  }
	  else if (!config.mountpoint) {
	    config.mountpoint = realpath(arg, NULL);
	    if (!config.mountpoint) {
	      fprintf(stderr, "bad mount point `%s': %s\n", arg, strerror(errno));
	      return -1;
	    }
	    return 0;
	  }
	  
	  fprintf(stderr, "invalid argument `%s'\n", arg);
	  return -2;
	default:
	  fprintf(stderr, "internal error\n");
	  abort();
	}
}

static int
read_passphrase(const char* prompt)
{
  D1("Reading passphrase from TTY");
  int err = 0;
  int size = getpagesize();
  int max_passphrase = MIN(MAX_PASSPHRASE, size - 1);
  int n, rppflags, ttyfd;

  config.passphrase = mmap(NULL, size, PROT_READ | PROT_WRITE,
			   MAP_PRIVATE | MAP_ANONYMOUS | MAP_LOCKED,
			   -1, 0);
  if (config.passphrase == MAP_FAILED) {
    perror("Failed to allocate locked page for passphrase");
    return -1;
  }
  if (mlock(config.passphrase, size) == -1) {
    perror("Failed to lock the page for passphrase");
    err = 1;
    goto error;
  }

  /* require a TTY */
  rppflags = RPP_ECHO_OFF | RPP_REQUIRE_TTY;
  ttyfd = open(_PATH_TTY, O_RDWR);
  if (ttyfd < 0){
    perror("can't open " _PATH_TTY);
    err = 2;
    goto error;
  }
  /*
   * If we're on a tty, ensure that show the prompt at
   * the beginning of the line. This will hopefully
   * clobber any passphrase characters the user has
   * optimistically typed before echo is disabled.
   */
  const char cr = '\r';
  (void) write(ttyfd, &cr, 1);
  close(ttyfd);

  /* read the passphrase */
  if(readpassphrase(prompt, config.passphrase, max_passphrase, rppflags) == NULL) {
    perror("can't read the passphrase");
    err = 3;
    goto error;
  }

  config.passphrase[strcspn(config.passphrase, "\r\n")] = '\0'; /* replace the CRLF */
  
  return 0;

error:
  memset(config.passphrase, 0, size);
  munmap(config.passphrase, size);
  config.passphrase = NULL;
  return err;
}

static int
c4gh_init(void)
{
  int res = 0;

  if(config.seckeypath == NULL){
    D1("Crypt4GH decryption disabled");
    return 0; // it's allowed
  }

  D1("Initializing Crypt4GH");
  D1("Secret key path: %s", config.seckeypath);

  if(*config.seckeypath != '/'){
    E("Secret key must be an absolute path");
    res ++;
    goto bailout;
  }

  /* Get the passphrase to unlock the Crypt4GH secret key */
  if (config.passphrase_from_env) {
    D2("Getting the passphrase from envvar %s", config.passphrase_from_env);
    config.passphrase = getenv(config.passphrase_from_env);
  } else {
    char prompt[PATH_MAX + sizeof("Enter the passphrase for the Crypt4GH key '': ")];
    sprintf(prompt, "Enter the passphrase for the Crypt4GH key '%s': ", config.seckeypath);
    if (read_passphrase(prompt) != 0){
      res ++;
      goto bailout;
    }
  }

  if(!config.passphrase){
    E("Missing passphrase");
    res ++;
    goto bailout;
  }

  /* Initialize libsodium */
  if (sodium_init() == -1) {
    E("Could not initialize libsodium: disabling Crypt4GH decryption");
    res ++;
    goto bailout;
  }

  /* Load the private key */
  D3("Loading secret key from %s", config.seckeypath);

  if( crypt4gh_sqlite_private_key_from_file(config.seckeypath, config.passphrase,
					    config.seckey, config.pubkey) ){
    E("Can't load the secret key from %s", config.seckeypath);
    res ++;
    goto bailout;
  }

  D3("Crypt4GH key loaded from '%s'", config.seckeypath);

bailout:
  return res;
}

static inline void
c4gh_destroy(void)
{
  sodium_memzero(config.seckey, crypto_kx_SECRETKEYBYTES);
  sodium_memzero(config.pubkey, crypto_kx_PUBLICKEYBYTES);
}


int main(int argc, char *argv[])
{

  int res = 0;
  struct fuse_args args = FUSE_ARGS_INIT(argc, argv);
  struct fuse *fuse;
  struct fuse_session *se;
  struct fuse_lowlevel_ops *operations;


  if(fuse_version() < FUSE_MAKE_VERSION(3,12) ){
    fprintf(stderr, "We need at least FUSE version %d\n", FUSE_MAKE_VERSION(3,12));
    fprintf(stderr, "You have FUSE version %d\n", fuse_version());
    return 1;
  }

  memset(&config, 0, sizeof(struct fs_config));

  config.progname = basename(argv[0]);
  config.mounted_at = time(NULL);

  //config.pid = getpid(); /* used in st_dev to distinguish from other FUSE file systems */
  config.created_at = config.mounted_at; /* default for creation time (stx_btime) */

  config.entry_timeout = DEFAULT_ENTRY_TIMEOUT;
  config.attr_timeout = DEFAULT_ATTR_TIMEOUT;
  config.max_threads = DEFAULT_MAX_THREADS;

  config.uid = getuid(); /* current user */
  config.gid = getgid(); /* current group */

  config.supp_gid = -1;

  D1("%s version %s", config.progname, PACKAGE_VERSION);

  /* General options */
  if (fuse_opt_parse(&args, &config, fs_opts, fs_opt_proc) == -1)
    exit(1);

  if(config.local_debug)
    config.foreground = 1;

  if (config.show_version) {
    printf("%s version %s\n", argv[0], PACKAGE_VERSION);
    printf("FUSE library version %s\n", fuse_pkgversion());
    fuse_lowlevel_version();
    exit(0);
  }
  if (config.show_help) {
    usage(&args);
    exit(0);
  }

  if (!config.db_path) {
    fprintf(stderr, "missing SQLite file\n");
    fprintf(stderr, "see `%s -h' for usage\n", config.progname);
    exit(1);
  } 
  if (!config.mountpoint) {
    fprintf(stderr, "error: no mountpoint specified\n");
    fprintf(stderr, "see `%s -h' for usage\n", config.progname);
    exit(1);
  }

  int save_err;
  if ( config.groupname ){
    save_err = errno;
    errno = 0;
    struct group *gr = getgrnam(config.groupname);
    if (gr == NULL){
      fprintf(stderr, "Invalid group name %s: %s\n", config.groupname, strerror(errno));
      fprintf(stderr, "see `%s -h' for usage\n", config.progname);
      exit(1);
    } else {
      config.gid = gr->gr_gid;
    }
    errno = save_err;
  }
  
  if ( config.username ){
    save_err = errno;
    errno = 0;
    struct passwd *user = getpwnam(config.username);
    if (user == NULL){
      fprintf(stderr, "Invalid user name %s: %s\n", config.username, strerror(errno));
      fprintf(stderr, "see `%s -h' for usage\n", argv[0]);
      exit(1);
    } else {
      config.uid = user->pw_uid;
    }
    errno = save_err;
  }

  if ( config.supp_group ){
    save_err = errno;
    errno = 0;
    struct group *gr = getgrnam(config.supp_group);
    if (gr == NULL){
      fprintf(stderr, "Invalid supplementary group %s: %s\n", config.supp_group, strerror(errno));
      fprintf(stderr, "see `%s -h' for usage\n", argv[0]);
      exit(1);
    } else {
      config.supp_gid = gr->gr_gid;
    }
    errno = save_err;
  }

  /* Afterwards */
  if ( config.uid < 0 )
    {
      fprintf(stderr, "Invalid user IDs\n");
      fprintf(stderr, "see `%s -h' for usage\n", config.progname);
      exit(1);
    }

  if ( config.gid < 0 )
    {
      fprintf(stderr, "Invalid group IDs\n");
      fprintf(stderr, "see `%s -h' for usage\n", config.progname);
      exit(1);
    }

  /* Must be root */
  if (getuid() || geteuid()) {
    fprintf(stderr, "You must be root to run \"%s\"\n", config.progname);
    return 1;
  }

  /* File and Dir permissions */
  mode_t mask = umask(0);
  umask(mask); /* restore */
  config.dperm = 0777 & ~mask;
  config.fperm = 0666 & ~mask;

  /* SQLite database */
  if(config.singlethread)
    sqlite3_config(SQLITE_CONFIG_SINGLETHREAD);
  else 
    sqlite3_config(SQLITE_CONFIG_MULTITHREAD);

  /* checking if the DB is writable */
  struct stat s;
  memset(&s, 0, sizeof(struct stat));
  if (fstatat(AT_FDCWD, config.db_path, &s, AT_NO_AUTOMOUNT) == -1){ // follow link
    E("Error stat(%s): %s", config.db_path, strerror(errno));
  } else {
    D1("stat(%s) mode: %o", config.db_path, s.st_mode);
    if((s.st_mode & S_IWUSR) == S_IWUSR) // owner-writable
      config.is_readwrite = 1;
  }
  
  D1("Opening SQLite path: %s (%s)", config.db_path, (config.is_readwrite) ? "read-write" : "read-only");
  sqlite3_open_v2(config.db_path, &config.db,
		  (config.is_readwrite ? SQLITE_OPEN_READWRITE : SQLITE_OPEN_READONLY)
		  | SQLITE_OPEN_FULLMUTEX,
		  NULL);
  if (config.db == NULL){
    E("Failed to allocate SQLite database handle"); 
    goto bailout;
  }
  if( sqlite3_errcode(config.db) != SQLITE_OK) {
    E("Failed to open DB: [%d] %s", sqlite3_extended_errcode(config.db), sqlite3_errmsg(config.db));
    goto bailout;
  }
  (void)sqlite3_extended_result_codes(config.db, 0); // no extended codes


#ifdef HAVE_STATX
  /* Get creation time */
  struct statx sx;
  memset(&sx, 0, sizeof(struct statx));

  if (statx(AT_FDCWD, config.db_path, AT_NO_AUTOMOUNT, STATX_BTIME, &sx) == -1){ // follow link
    E("Error statx(%s): %s", config.db_path, strerror(errno));
  } else {
    if(sx.stx_mask & STATX_BTIME) // we got a btime
      config.created_at = sx.stx_btime.tv_sec;
  }
#endif

  /* Crypt4GH options */
  if(c4gh_init()){
    E("Parsing Crypt4GH options");
    res = 1;
    goto bailout;
  }

  operations = fs_operations();

  /* disable if you can't write in the DB file */
  if(!config.is_readwrite){
    operations->setxattr = NULL;
    operations->removexattr = NULL;
  }

  /* If we don't specify the supplementary group,
   * we drop all of them.
   * If we do, it's the only allowed one.
   *
   * Note: https://man7.org/linux/man-pages/man2/setgroups.2.html
   */
  int ngroups = 0;
  gid_t groups[1];

  if(config.supp_gid >= 0){
    groups[ngroups++] = config.supp_gid;
    D1("Supplementary group: %d", config.supp_gid);
  }

  if(setgroups(ngroups, groups)){
    if(ngroups == 0)
      D1("Error dropping groups: %s", strerror(errno));
    else
      D1("Error setting group %d: %s", groups[0], strerror(errno));
    res = 2;
    goto bailout;
  }

  /* Drop privileges / capabilities */
  cap_t caps;
  cap_value_t cap_fowner = CAP_FOWNER;
  if (!(caps = cap_init())
      || cap_clear(caps) == -1
      || cap_set_flag(caps, CAP_PERMITTED, 1, &cap_fowner, CAP_SET) == -1
      || cap_set_flag(caps, CAP_EFFECTIVE, 1, &cap_fowner, CAP_SET) == -1
      || cap_set_proc(caps) == -1) {
    D1("Error dropping capabilities: %s", strerror(errno));
    res = 2;
    goto bailout;
  }
  cap_free(caps);

  cap_t verify_caps = NULL;
  char *cap_str = NULL;
  if (!(verify_caps = cap_get_proc())
      || !(cap_str = cap_to_text(verify_caps, NULL))){
    D1("Error getting capabilities: %s", strerror(errno));
  } else {
    D1("capabilities: %s", cap_str);
  }
  cap_free(verify_caps);
  cap_free(cap_str);


  /* FUSE loop */
  D1("Starting the FUSE session");
  se = fuse_session_new(&args, operations, sizeof(struct fuse_lowlevel_ops), NULL); //&config
  if (se == NULL){
    res = 3;
    goto bailout;
  }

  D2("Setting up signal handlers");
  if (fuse_set_signal_handlers(se) != 0) {
    res = 4;
    goto bailout_destroy;
  }

  D2("Mounting %s", config.mountpoint);
  if (fuse_session_mount(se, config.mountpoint) != 0) {
    res = 5;
    goto bailout_signal;
  }
  
  D2("Deamonize: %s", (config.foreground)?"no":"yes");
  if (fuse_daemonize(config.foreground) == -1) {
    res = 6;
    goto bailout_unmount;
  }

  config.pid = getpid();
  D2("PID: %d", config.pid);
  D2("File cache: %s | Dir cache: %s | File perm: o%o | Dir perm: o%o",
     (config.file_cache)?"yes":"no",
     (config.dir_cache)?"yes":"no",
     config.fperm,
     config.dperm);
  D2_("Mounted at: %s", ctime(&config.mounted_at));
  D2_("Created at: %s", ctime(&config.created_at));

  if (config.singlethread){
    D2("Running single-threaded fuse loop");
    res = fuse_session_loop(se);
  } else {
    D2("Running multi-threaded fuse loop | max threads: %d", config.max_threads);
    struct fuse_loop_config *cf = fuse_loop_cfg_create();
    fuse_loop_cfg_set_clone_fd(cf, config.clone_fd);
    fuse_loop_cfg_set_max_threads(cf, config.max_threads);
    res = fuse_session_loop_mt(se, cf);
    fuse_loop_cfg_destroy(cf);
  }

  D2("Fuse loop exited");

 bailout_unmount:
  D2("Unmounting");
  (void)chdir("/");
  fuse_session_unmount(se);

  //(void)umount2(config.mountpoint, MNT_DETACH); /* lazy umount */

 bailout_signal:
  D2("Removing signal handlers");
  fuse_remove_signal_handlers(se);

 bailout_destroy:
  D1("Destroying");
  fuse_session_destroy(se);

 bailout:
  D1("Exiting with status %d", res);

  fuse_opt_free_args(&args);

  c4gh_destroy();
  if(config.db) sqlite3_close(config.db);
  if(config.db_path) free(config.db_path);
  if(config.mountpoint) free(config.mountpoint);

  return res;
}

