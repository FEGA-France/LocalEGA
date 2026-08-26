# EGA NSS over (caching) files

We export DB data into files using [triggers](../db/53-nss-triggers.sql).

| NSS database | data type | filepath                   | mode | owner | group |
|--------------|-----------|----------------------------|------|-------|-------|
| passwd       | users     | `${ETC_DIR}/nss/users`     | 644  | root  | root  |
| group        | groups    | `${ETC_DIR}/nss/groups`    | 644  | root  | root  | 
| shadow       | passwords | `${ETC_DIR}/nss/passwords` | 640  | root  | shadow  |

where `${ETC_DIR}` is `/opt/LocalEGA/etc` on the host and `/etc/ega` in the vault-db container.

Moreover, we cache the authorized ssh keys for each user in `${ETC_DIR}/authorized_keys/<username>`.

If the files are pre-created with the right permissions, the postgres user in the database would update their content, and not re-create the files.  
In particular the shadow/passwords files should be group-owned by the group `shadow` and only readable by that group, and not world-accessible).

## Build

	make
	sudo make install EGA_LIBDIR=/opt/LocalEGA/lib
	
Become the root user and run the commands to make the library discoverable:

	echo '/opt/LocalEGA/lib' > /etc/ld.so.conf.d/ega.conf
	ldconfig -v

Then update `/etc/nsswitch.conf` with:

	passwd:         files egafiles systemd
	group:          files egafiles systemd
	shadow:         files egafiles

## Examples

	# See a user entry
	getent passwd -s egafiles silverdaz

	# See a user password
	getent shadow -s egafiles silverdaz

	# See the whole shebang for a user
	id silverdaz

	# See the group entry
	getent group -s egafiles requesters

	# See the group entry, without the members
	getent group -s egafiles requesters | awk -F: '{ print $1 ":" $3 }'


## Debug version

	make clean debugN # where N is 1, 2 or 3
	

# SSH configuration

Since the files in `/etc/ega/cache/authorized_keys/` are not owned by the respective user, ssh would not use them as `AuthorizedKeysFile`, although they are not group not world writable. See the [check in the source code](https://github.com/openssh/openssh-portable/blob/50b9e4a4514697ffb9592200e722de6b427cb9ff/misc.c#L2188-L2193).

Therefore, we do not use `AuthorizedKeysFile` and we use the combination of `AuthorizedKeysCommand` and `AuthorizedKeysCommandUser`, in `sshd_config`

	AuthorizedKeysCommand cat /opt/LocalEGA/etc/authorized_keys/%u
	# %u is the TOKEN for the username
	AuthorizedKeysCommandUser lega
	# because it's actually uid 999, which is postgres _inside_ the database container
	
