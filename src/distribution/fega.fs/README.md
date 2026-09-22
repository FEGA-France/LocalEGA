[![GitHub CI](https://github.com/FEGA-France/crypt4gh-sqlite.fs/actions/workflows/build.yml/badge.svg)](https://github.com/FEGA-France/crypt4gh-sqlite.fs/actions/workflows/build.yml)


# Crypt4GH file system over an SQLite database


Requirements:
* [libsodium](https://doc.libsodium.org)
* OpenSSL
* [Fuse 3](https://github.com/libfuse/libfuse)


## Install

	autoreconf
	./configure
	make
	sudo make install

## Example

We include a simple [example](example). It shows how to prepend/append data, decrypt a Crypt4GH file, or not (ie passthrough).
