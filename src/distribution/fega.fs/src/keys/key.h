/**********************************************************************************
 * Read-only Crypt4GH file system, listing information from an SQLite "database".
 *
 *  Author:  Frédéric Haziza <silverdaz@gmail.com>
 *    Date:  October 2023
 *
 *  This program can be distributed under the terms of the GNU Affero GPL.
 *  See the LICENSE file.
 **********************************************************************************/

#ifndef _CRYPT4GH_SQLITE_KEY_H
#define _CRYPT4GH_SQLITE_KEY_H 1

int
crypt4gh_sqlite_private_key_from_file(const char* filename,
			  char* passphrase,
			  uint8_t seckey[crypto_kx_SECRETKEYBYTES],
			  uint8_t pubkey[crypto_kx_PUBLICKEYBYTES]);

#endif
