# EGA PAM

## installation

	make
	sudo make install

## How it is built

The login logic for the outbox is as follows:

1) PAM gives us the username
2) Find the pwd struct with NSS: we get uid, gid, and homedir  
   -> bail out if not found
3) Check public key(s) and then password hash


4) Home dir:
   * If not exists: create it, including the "[homedir]/outbox"
   * homedir is owned by root:gid with mode 550 (forced: see chrooting below)
   * outbox is owned by uid,gid with attrs=500 (configurable)
   * Create [homedir]/etc/{passwd,group} just to print uid,gid nicely
5) FUSE mountpoint
   * if already mounted on <homedir>/subdir: do nothing and return success
   * (Assume home dir is fine)
   * fork
   * For the child
     - drop privileges to uid,gid in the child
	 - add eventual supplementary groups
     - detach itself (daemon)
     - set umask
     - Swap for the fuse exec (run then by uid,gid): Mount fuse code, using an already opened file descriptor
   * For the parent:
     - checks that the child has not exited


----

sftp or aspera will change directory to /subdir, once started (and working in a chroot environment).

Vault files are readable by at least one of the injected supplementary groups.

The fuse executable runs as the user (uid and gid), and it needs "allow\_root" (which in turn needs "allow\_other").


----

We implemented the following modules

| Module   | Name               | Action |
|---------:|:-------------------|:-------|
| auth     | pam\_ega\_auth     | Checks password in the Blowfish or standard format |
| account  | pam\_ega\_homedir  | Create the home directory (fetched from NSS), and subdirectory, including permissions |
| account  | pam\_ega\_fusedir  | Create the fuse directory including ACLs |
| account  | pam\_ega\_localnss | Inject /etc/{passwd,group} files for nss resolution with chrooted |
| session  | pam\_ega\_session  | Mount the FUSE file system and set umask |
| password | -              | denied |

with the following options:

* debug
* silent
* subdir=outbox (default: 'home')
* attrs=<mode> (default: 500)
* prompt=<str>  (default: "Please, enter your EGA password: ")
* use_first_pass
* try_first_pass
* unmount_on_close
* umask=<octal> (default: 277)
* bail_on_exists
* conf=/etc/ega/fs.conf

For the PAM session, we end the command line with `--`,  
what follows is the fuse command, minus the mountpoint. The latter will be appended.
There is no default


## Improvements

After the fuse daemon is started, the parent might need to wait a bit for the python code to kick in.
We could use a pipe to communicate with the parent and close the pipe when fuse is ready, effectively replacing the `waitpid` call.
