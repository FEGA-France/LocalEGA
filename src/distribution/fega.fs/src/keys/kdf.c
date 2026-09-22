/**********************************************************************************
 * Read-only Crypt4GH file system, listing information from an SQLite "database".
 *
 *  Author:  Frédéric Haziza <silverdaz@gmail.com>
 *    Date:  October 2023
 *
 *  This program can be distributed under the terms of the GNU Affero GPL.
 *  See the LICENSE file.
 **********************************************************************************/

#include "includes.h"

#include <openssl/evp.h>

#include "keys/kdf.h"

#ifndef HAVE_BCRYPT_PBKDF
int bcrypt_pbkdf(const char *, size_t, const u_int8_t *, size_t, u_int8_t *, size_t, unsigned int);
#endif


/* Supported key types */
static const struct kdftype kdfs[] = {
  {              "scrypt", 16, 0      },
  {              "bcrypt", 16, 100    },
  { "pbkdf2_hmac_sha256'", 16, 100000 },
  { NULL, 0, 0 }
};

const struct kdftype *
crypt4gh_sqlite_kdf_from_name(const char* name, size_t name_len)
{
  const struct kdftype *kt;
  for (kt = kdfs; kt->name != NULL; kt++) {
    if (!strncmp(kt->name, name, name_len))
      return kt; /* points to static allocation */
  }
  return NULL;
}


int
crypt4gh_sqlite_kdf_derive_key(char* alg,
			       uint8_t *key, size_t key_len,
			       const char* passphrase, size_t passphrase_len,
			       uint8_t* salt, size_t salt_len,
			       int rounds)
{
  /* See https://www.rfc-editor.org/rfc/rfc7914.txt
     and https://doc.libsodium.org/advanced/scrypt#notes */
  if (!strncmp(alg, "scrypt", 6)){
    D3("Deriving a shared key using scrypt");
    return crypto_pwhash_scryptsalsa208sha256_ll((const uint8_t*)passphrase, passphrase_len,
						 salt, salt_len,
						 1<<14, 8, 1,
						 key, key_len);
  }

  /* See keys/bcrypt
     and https://github.com/pyca/bcrypt/tree/master/src/_csrc */
  if (!strncmp(alg, "bcrypt", 6)){
    D3("Deriving a shared key using scrypt");
    return bcrypt_pbkdf(passphrase, passphrase_len,
			salt, salt_len,
			key, key_len,
			rounds);
  }

  /* See https://www.openssl.org/docs/man1.1.0/man3/PKCS5_PBKDF2_HMAC.html */
  if (!strncmp(alg, "pbkdf2_hmac_sha256", 18)){
    D3("Deriving a shared key using HMAC-SHA256");
    const EVP_MD *digest = EVP_sha256();
    if(digest == NULL) return 3;
    int rc = PKCS5_PBKDF2_HMAC(passphrase, passphrase_len,
			       salt, salt_len,
			       rounds,
			       digest,
			       key_len,
			       key)?0:1; /* ah bravo openssl: 1 on success, 0 on error ! */
    /* shouldn't we free the digest? Or is it done by openssl? */
    return rc;
  }

  D1("Unsupported KDF: %s", alg);
  return -1;
}
