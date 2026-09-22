/**********************************************************************************
 * Read-only Crypt4GH file system, listing information from an SQLite "database".
 *
 *  Author:  Frédéric Haziza <silverdaz@gmail.com>
 *    Date:  October 2023
 *
 *  This program can be distributed under the terms of the GNU Affero GPL.
 *  See the LICENSE file.
 **********************************************************************************/

#ifndef __CRYPT4GH_SQLITE_KDF_H_INCLUDED__
#define __CRYPT4GH_SQLITE_KDF_H_INCLUDED__

/* Supported key types */
struct kdftype {
	const char *name;
	int saltsize;
	int rounds;
};

const struct kdftype*
crypt4gh_sqlite_kdf_from_name(const char* name, size_t name_len);

int
crypt4gh_sqlite_kdf_derive_key(char* alg,
			       unsigned char *key, size_t key_len,
			       const char* passphrase, size_t passphrase_len,
			       unsigned char *salt, size_t salt_len,
			       int rounds);

#endif /* ! __CRYPT4GH_SQLITE_KDF_H_INCLUDED__ */
