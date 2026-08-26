
#include "includes.h"

#include <pwd.h>

#define DEFAULT_MAX_IDLE_THREADS 10
#define DEFAULT_MAX_CONNECTIONS  2

extern const struct fuse_lowlevel_ops ega_dist_operations;


#define EGA_OPT(t, p, v) { t, offsetof(struct ega_config, p), v }

static struct fuse_opt ega_opts[] = {

  EGA_OPT("-h",		show_help, 1),
  EGA_OPT("--help",	show_help, 1),
  EGA_OPT("-V",		show_version, 1),
  EGA_OPT("--version",	show_version, 1),
  EGA_OPT("-f",		foreground, 1),
  
  EGA_OPT("parent_fd=%u", parent_fd, -1),
  EGA_OPT("conf_fd=%u", conf_fd, -1),
  EGA_OPT("max_connections=%u", size, 0),

  /* if multithreaded */
  EGA_OPT("-s"              , singlethread    , 1),
  EGA_OPT("clone_fd"        , clone_fd        , 1),
  EGA_OPT("max_idle_threads=%u", max_idle_threads, 0),


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
ega_opt_proc(void *data, const char *arg, int key, struct fuse_args *outargs)
{
	(void) outargs;
	struct ega_config* config = (struct ega_config*) data;
	char *tmp;

	switch (key) {
	case FUSE_OPT_KEY_OPT:
	  /* Pass through */
	  return 1;

	case FUSE_OPT_KEY_NONOPT:
	  /* last arg: mount pattern */
	  if (!config->mountpoint) {
	    config->mountpoint = realpath(arg, NULL);
	    return 0;
	  }
	  
	  fprintf(stderr, "invalid argument `%s'\n", arg);
	  return -1;


	default:
	  fprintf(stderr, "internal error\n");
	  abort();
	}
}


int
main(int argc, char *argv[])
{

  int ret = -1;
  struct fuse_args args = FUSE_ARGS_INIT(argc, argv);
  struct fuse_session *se;
  struct ega_config config;

  memset(&config, 0, sizeof(struct ega_config));

  config.uid = getuid();
  config.gid = getgid();
  config.mounted_at = time(NULL);
  /* Set the defaults */
  config.max_idle_threads = DEFAULT_MAX_IDLE_THREADS;
  config.conf_fd = -1;
  config.parent_fd = -1;
  config.size = DEFAULT_MAX_CONNECTIONS;

  /* General options */
  if (fuse_opt_parse(&args, &config, ega_opts, ega_opt_proc) == -1){
    ret = 1;
    goto bailout;
  }

  if (config.show_help) {
    printf("usage: %s [options] <mountpoint>\n\n", argv[0]);
    fuse_cmdline_help();
    fuse_lowlevel_help();
    ret = 0;
    goto bailout;
  } else if (config.show_version) {
    printf("FUSE library version %s\n", fuse_pkgversion());
    fuse_lowlevel_version();
    ret = 0;
    goto bailout;
  }

  if (config. conf_fd < 0 ) {
    E("Invalid configuration file descriptor");
    ret = 2;
    goto bailout;
  }
  if(config.mountpoint == NULL) {
    printf("usage: %s [options] --conf <fd> <mountpoint>\n", argv[0]);
    printf("       %s --help\n", argv[0]);
    ret = 3;
    goto bailout;
  }


  struct passwd* user = getpwuid(config.uid); /* do not free */
  if(user == NULL){
    fprintf(stderr, "Can't find user %u\n", config.uid);
    ret = 4;
    goto bailout;
  }

  config.username = strdup(user->pw_name);
  if (config.username == NULL || errno == ENOMEM) {
    ret = 5;
    goto bailout;
  }
  config.username_len = strlen(config.username);

  D1("Current user  : %s [%u/%u]", config.username, config.uid, config.gid);
  D1("Mountpoint    : %s", config.mountpoint);

  /* Load the config */
  if (ega_dist_loadconfig(&config)){
    E("Can't load the configuration file");
    ret = 6;
    goto bailout;
  }

  /* fuse session */
  se = fuse_session_new(&args, &ega_dist_operations, sizeof(ega_dist_operations), &config);

  if (se == NULL)
    goto bailout;

  if (fuse_set_signal_handlers(se) != 0)
    goto bailout_session;

  if (fuse_session_mount(se, config.mountpoint) != 0)
    goto bailout_signal;

  /* Notify the parent */
  if(config.parent_fd > 0){
    char data= '1';
    if(write(config.parent_fd, &data, 1) != 1){
      E("Error writing back to the parent: %s", strerror(errno));
      ret = 7;
      goto bailout_unmount;
    }
    close(config.parent_fd);
    config.parent_fd = -1;
  }

  if (config.singlethread){
    D1("Single threaded mode");
    ret = fuse_session_loop(se);
  } else {
    struct fuse_loop_config conf = {
      .clone_fd = config.clone_fd,
      .max_idle_threads = config.max_idle_threads
    };
    ret = fuse_session_loop_mt(se, &conf);
  }

  if(ret)
    ret = 8;

bailout_unmount:
  fuse_session_unmount(se);

bailout_signal:
  fuse_remove_signal_handlers(se);

bailout_session:
  fuse_session_destroy(se);

bailout:
  D1("Exiting with status %d", ret);

  fuse_opt_free_args(&args);

  ega_dist_cleanconfig(&config);
  return ret;
}
