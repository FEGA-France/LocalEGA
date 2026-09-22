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

#include <ctype.h> /* isspace */

#include "keys/kdf.h"

/*
 * Prints byte array to its hexadecimal representation
 */
#ifdef NO_DEBUG
#define Dhex(leading, v, len)
#else
#define Dhex(leading, v, len) if(config.local_debug > 2) {		\
    fprintf(stderr, "#           %s: ", leading);			\
    size_t _i = 0;							\
    uint8_t* _p = (uint8_t*)v;						\
    for(;_i<len;_i++){ fprintf(stderr, "%02x", _p[_i] ); }		\
    fprintf(stderr, "\n");						\
  }
#endif

/* ==================================================================
 *
 *  Public key
 *
 * ================================================================== */

#define MARK_PUBLIC_BEGIN	"-----BEGIN CRYPT4GH PUBLIC KEY-----\n"
#define MARK_PUBLIC_END         "-----END CRYPT4GH PUBLIC KEY-----"
#define MARK_PUBLIC_BEGIN_LEN	(sizeof(MARK_PUBLIC_BEGIN) - 1)
#define MARK_PUBLIC_END_LEN	(sizeof(MARK_PUBLIC_END) - 1)

/*
 * The line should start with MARK_PUBLIC_BEGIN and end with MARK_PUBLIC_END
 */
static int
crypt4gh_sqlite_public_key_from_blob(const char* line,
				     size_t len,
				     uint8_t pk[crypto_kx_PUBLICKEYBYTES])
{
  int rc = 1;
  char* end = (char*)line + len - 1; /* point at the end */
  D3("Length: %lu", len);
  //D3("Last char: %c", *end);

  while(isspace(*line)){ line++; len--; }; /* skip leading white-space (or newline) */
  while(isspace(*end)){ end--; len--; }; /* Discount trailing white-space or newline */

  D3("Real length: %lu", len);

  if(/* large enough */
     len <= MARK_PUBLIC_BEGIN_LEN + MARK_PUBLIC_END_LEN 
     || /* starts with MARK_PUBLIC_BEGIN */
     memcmp(line, MARK_PUBLIC_BEGIN, MARK_PUBLIC_BEGIN_LEN) 
     || /* ends with MARK_PUBLIC_END */
     memcmp(line + len - MARK_PUBLIC_END_LEN, MARK_PUBLIC_END, MARK_PUBLIC_END_LEN)
     )
    {
      W("Not a C4GH-v1 key");
      return 1;
    }

  /* Skip the MARK_PUBLIC_BEGIN and any white-space and newline */
  line += MARK_PUBLIC_BEGIN_LEN;
  len -= MARK_PUBLIC_BEGIN_LEN;
  while(isspace(*line)){ line++; len--; }; /* skip leading white-space or newline */

  /* Discount the MARK_PUBLIC_END and any white-space and newline */
  len -= MARK_PUBLIC_END_LEN;
  end = (char*)line + len - 1; /* point at the end */
  while(isspace(*end)){ end--; len--; }; /* Discount trailing white-space or newline */

  /* Copy the base64 part and add a NULL-terminating character (cuz we can't change "line") */
  char tmp[len+1];
  memcpy(tmp, line, len);
  tmp[len] = '\0';
  D3("base64 string: %s", tmp);

  /* Decoded string will be NULL-terminated too */
  u_char tmp2[crypto_kx_PUBLICKEYBYTES+1];
  int nlen = b64_pton(tmp, tmp2, crypto_kx_PUBLICKEYBYTES+1);
  D3("base64 decoding: %d", nlen);
  if(nlen < 0 || nlen < crypto_kx_PUBLICKEYBYTES){
    E("Error with base64 decoding");
    rc = 2;
  } else {
    /* Success: copy over without the NULL-terminating char */
    memcpy(pk, tmp2, crypto_kx_PUBLICKEYBYTES);
    rc = 0;
  }

  /* Public information: no need to zero it */
  return rc;
}


/* ==================================================================
 *
 *  Private key, locked or not
 *
 * ================================================================== */

#define MAGIC_WORD      "c4gh-v1"

#define MARK_PRIVATE_BEGIN	"-----BEGIN CRYPT4GH PRIVATE KEY-----\n"
#define MARK_PRIVATE_END         "-----END CRYPT4GH PRIVATE KEY-----\n"
#define MARK_PRIVATE_BEGIN_LEN	(sizeof(MARK_PRIVATE_BEGIN) - 1)
#define MARK_PRIVATE_END_LEN	(sizeof(MARK_PRIVATE_END) - 1)

/*
 * Read 4 bytes from p and 
 * get its integer representation in little-endian format
 */
#define PEEK_U32_BE(p) \
	(((uint32_t)(((const uint8_t *)(p))[0]) << 24) | \
	 ((uint32_t)(((const uint8_t *)(p))[1]) << 16) | \
	 ((uint32_t)(((const uint8_t *)(p))[2]) << 8 ) | \
	 ((uint32_t)(((const uint8_t *)(p))[3])      ))


/** Consumes a string. 
 *  The string length is encoded in the 2 first bytes, as big-endian
 *  Advances the pointer bufp
 */
static int
decode_string(u_char** bufp, u_char **valp, uint16_t *lenp)
{
  if(bufp == NULL) return 1;
  u_char* buf = *bufp;

  /* string length is encoded in the 2 first bytes, as big-endian */
  uint16_t slen = ((uint8_t)(buf[0]) << 8) | (uint8_t)(buf[1]);
  if(valp) *valp = buf + 2;  /* save the start */
  if(lenp) *lenp = slen;   /* save the length */

  *bufp += slen + 2; /* make it consumed */
  return 0;
}


/*
 * The line should start with MARK_PRIVATE_BEGIN and end with MARK_PRIVATE_END
 */
static int
crypt4gh_sqlite_private_key_from_blob(char* line, size_t len,
				      char* passphrase,
				      uint8_t seckey[crypto_kx_SECRETKEYBYTES],
				      uint8_t pubkey[crypto_kx_PUBLICKEYBYTES])
{
  int rc = 1;
  char *end = line + len; /* point at the end */
  u_char *tmp = NULL, *p = NULL;
  uint8_t* shared_key = NULL;

  if(/* large enough */
     len <= MARK_PRIVATE_BEGIN_LEN + MARK_PRIVATE_END_LEN 
     || /* starts with MARK_PRIVATE_BEGIN */
     memcmp(line, MARK_PRIVATE_BEGIN, MARK_PRIVATE_BEGIN_LEN) 
     || /* ends with MARK_PRIVATE_END */
     memcmp(end - MARK_PRIVATE_END_LEN, MARK_PRIVATE_END, MARK_PRIVATE_END_LEN)
     )
    {
      E("Not a Crypt4GH private key");
      rc = 1;
      goto bailout;
    }

  /* Skip the MARK_PUBLIC_BEGIN and any white-space and newline */
  line += MARK_PRIVATE_BEGIN_LEN;
  len -= MARK_PRIVATE_BEGIN_LEN;
  while(isspace(*line)){ line++; len--; }; /* skip leading white-space or newline */

  /* Discount the MARK_PUBLIC_END and any white-space and newline */
  len -= MARK_PRIVATE_END_LEN;
  end = line + len - 1; /* point at the end */
  while(isspace(*end)){ end--; len--; }; /* Discount trailing white-space or newline */

  /* we _can_ change "line" */
  *(end+1) = '\0';

  D3("base64 string: %s", line);

  /* Decoded string will be NULL-terminated too */
  tmp = (u_char*)malloc((len+1) * sizeof(char));
  int nlen = b64_pton(line, tmp, len+1);
  D3("base64 decoding: %d", nlen);
  if(nlen < 0){
    E("Error with base64 decoding");
    rc = 4;
    goto bailout;
  }

  if(memcmp(tmp, MAGIC_WORD, sizeof(MAGIC_WORD) - 1)){
    E("Invalid magic word");
    rc = 5;
    goto bailout;
  }

  /* record start */
  p = tmp + sizeof(MAGIC_WORD) - 1;

  char* kdfname = NULL;
  uint16_t kdfname_len = 0;
  decode_string(&p, (u_char**)&kdfname, &kdfname_len);

  D2("KDF name: %.*s", (int)kdfname_len, kdfname);
  u_char* salt = NULL;
  uint16_t salt_len = 0;
  uint32_t rounds = 0;

  if(strncmp(kdfname, "none", kdfname_len))
    { /* not none... so get the saltsize and rounds */

      /* get KDF options */
      u_char* kdfoptions = NULL;
      uint16_t kdfoptions_len = 0;
      decode_string(&p, &kdfoptions, &kdfoptions_len);

      /* get rounds as 4 big-endian bytes */
      if( kdfoptions_len < 4){ rc = 2; goto bailout; }
      rounds = (((uint32_t)(kdfoptions[0]) << 24) | 
		((uint32_t)(kdfoptions[1]) << 16) |
		((uint32_t)(kdfoptions[2]) <<  8) |
		((uint32_t)(kdfoptions[3])      ) );
      D3("Rounds: %d", rounds);
      /* get the salt */
      salt_len = kdfoptions_len-4;
      salt = kdfoptions+4;
      Dhex("Salt", salt, salt_len);
    }
  else
    {
      W("Not encrypted");
    }

  char* ciphername = NULL;
  uint16_t ciphername_len = 0;
  decode_string(&p, (u_char**)&ciphername, &ciphername_len);
  D2("Ciphername: %.*s", (int)ciphername_len, ciphername);

  u_char* private_data = NULL;
  uint16_t private_data_len = 0;
  decode_string(&p, &private_data, &private_data_len);

  Dhex("Private data", private_data, private_data_len);

  if(strncmp(ciphername, "none", ciphername_len) == 0)
    {
      /* No encryption: the private data is the secret key */
      memcpy(seckey, private_data,
	     /* use the min */
	     (private_data_len < crypto_kx_SECRETKEYBYTES)?private_data_len:crypto_kx_SECRETKEYBYTES);
      goto pubkey;
    }

#if 0
  /* We have encrypted data, start libsodium */
  if (sodium_init() == -1) {
    D1("Unable to initialize libsodium");
    rc = 127;
    goto bailout;
  }
#endif

  shared_key = (uint8_t*)sodium_malloc(crypto_kx_SESSIONKEYBYTES /* 32 */);
  if( (rc = crypt4gh_sqlite_kdf_derive_key(kdfname,
					   shared_key, crypto_kx_SESSIONKEYBYTES /* 32 */,
					   passphrase, strlen(passphrase), salt, salt_len, rounds)) != 0)
    {
      D1("Error deriving the shared key: %d", rc);
      goto bailout;
    }
  sodium_mprotect_readonly(shared_key);
  Dhex("Shared key", shared_key, crypto_kx_SESSIONKEYBYTES);

  u_char nonce[12];
  memcpy(nonce, private_data, 12);
  Dhex("Nonce", nonce, 12);
  D3("Encrypted data length: %d", (private_data_len - 12));

  unsigned long long decrypted_len;
  if( (rc = crypto_aead_chacha20poly1305_ietf_decrypt(seckey, &decrypted_len,
						 NULL,
						 private_data + 12, private_data_len - 12,
						 NULL, 0, /* no authenticated data */
						 nonce, shared_key)) != 0)
    {
      E("Error decrypting the private data: %d", rc);
      D3("outlen: %llu", decrypted_len);
      goto bailout;
    }

  D3("outlen: %llu", decrypted_len);

pubkey:
  /* derive the public key */
  rc = crypto_scalarmult_base(pubkey, seckey);

bailout:
  if(tmp) free(tmp);
  if(shared_key) sodium_free(shared_key);
  return rc;
}


/* ==================================================================
 *
 *  Private key from file
 *
 * ================================================================== */

int
crypt4gh_sqlite_private_key_from_file(const char* filename,
				      char* passphrase,
				      uint8_t seckey[crypto_kx_SECRETKEYBYTES],
				      uint8_t pubkey[crypto_kx_PUBLICKEYBYTES])
{
  int rc = 1;
  char* buf = NULL;
  char *start = NULL, *end = NULL;
  size_t len = 0, buflen = 0, left = 0;
  int fd = -1;

  D2("Opening file: %s", filename);
  if ((fd = open(filename, O_RDONLY)) == -1){
    E("Can't open('%s'): [%d] %s", filename, errno, strerror(errno) );
    return 1;
  }

  struct stat sb;
  if(fstat(fd, &sb)){
    E("Can't stat filename '%s': [%d] %s", filename, errno, strerror(errno) );
    return 1;
  }
  buflen = sb.st_size;

#ifdef HAVE_MMAP
  buf = mmap(NULL, buflen, PROT_READ, MAP_SHARED, fd, 0);
  if (buf == MAP_FAILED){
    E("mmap failed for input: %d | %s", errno, strerror(errno));
    rc = 1;
    goto bailout;
  }
#else
  /* Read file into the buffer */
  buf = calloc(buflen, sizeof(char));
  if(buf == NULL){
    E("Error allocating a buffer of size %zu", buflen);
    rc = 1;
    goto bailout;
  }

  start = buf;
  while (buflen > 0) {
    rc = read(fd, start, buflen);
    if (rc == -1) { /* error */
      E("Error reading file: %s", strerror(errno));
      rc = 2;
      goto bailout;
    }
    if (rc == 0) /* no more to read */
      break;

    buflen -= rc;
    start += rc;
    len += rc;
  }
#endif

  /* We now stripped the file content from white-spaces */
  D3("Content from %s | %.*s", filename, (int)len, buf);

  rc = crypt4gh_sqlite_private_key_from_blob(buf, len, passphrase, seckey, pubkey);

#ifndef HAVE_MMAP
  freezero(buf, buflen);
#endif

bailout:
  if(fd > 0) close(fd);
  if(rc){ E("Failed parsing %s: Error %d", filename, rc); }
  return rc;
}
