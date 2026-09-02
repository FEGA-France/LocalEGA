/* #define DEBUG 3 */
/* #include "debug.h" */

#include "includes.h"

#include <sys/types.h>
#include <errno.h>
#include <strings.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <ctype.h> /* for isspace */

static inline int copy2buffer(const char* data, char** dest, char **bufptr, size_t *buflen);

void
ega_dist_cleanconfig(struct ega_config* options)
__attribute__((nonnull))
{
  if(options->buffer){ free(options->buffer); }
  options->buffer = NULL;
  if(options->username){ free(options->username); }
  options->username = NULL;
  if(options->mountpoint) free(options->mountpoint);
  options->mountpoint = NULL;
  if(options->conf_fd > 0) close(options->conf_fd);
  if(options->parent_fd > 0) close(options->parent_fd);
}


static int
valid_options(struct ega_config* options)
{
  int invalid = 0;
  if(!options) { E("No config struct"); return 1; }

  if(!options->conninfo      ) { D1("Missing connection info");invalid++; }

  if(!options->lookup   ) { D1("Missing lookup");    invalid++; }
  if(!options->readdir  ) { D1("Missing readdir");   invalid++; }
  if(!options->getattr  ) { D1("Missing getattr");   invalid++; }
  if(!options->file_info) { D1("Missing file_info"); invalid++; }
  if(!options->statfs   ) { D1("Missing statfs");    invalid++; }

  D3("Connection dsn : %s", options->conninfo);
  D3("lookup query   : %s", options->lookup);
  D3("readdir query  : %s", options->readdir);   
  D3("getattr lookup : %s", options->getattr);
  D3("file_info query: %s", options->file_info);     
  D3("getxattr lookup: %s", options->getxattr);
  D3("   statfs query: %s", options->statfs);

  if(invalid){
    E("Invalid config struct");
    ega_dist_cleanconfig(options);
  }
  return invalid;
}

#define INJECT_OPTION(key,ckey,val,loc) do { if(!strcmp(key, ckey)                             \
					        && copy2buffer(val, loc, &buffer, &buflen) < 0 \
                                               ){ return -1; }                                 \
                                           } while(0)
#define COPYVAL(val,dest,b,blen) do { if( copy2buffer(val, dest, b, blen) < 0 ){ return -1; } } while(0)

static inline int
readconfig(FILE* fp, struct ega_config* options, char* buffer, size_t buflen)
{
  D3("Reading configuration file");
  char* line = NULL;
  size_t len = 0;
  char *key,*eq,*val,*end;

  /* Parse line by line */
  while (getline(&line, &len, fp) > 0) {

    key=line;
    /* remove leading whitespace */
    while(isspace(*key)) key++;
      
    if((eq = strchr(line, '='))) {
      end = eq - 1; /* left of = */
      val = eq + 1; /* right of = */
	  
      /* find the end of the left operand */
      while(end > key && isspace(*end)) end--;
      *(end+1) = '\0';
	  
      /* find where the right operand starts */
      while(*val && isspace(*val)) val++;
	  
      /* find the end of the right operand */
      eq = val;
      while(*eq != '\0') eq++;
      eq--;
      if(*eq == '\n') { *eq = '\0'; } /* remove new line */
	  
    } else val = NULL; /* could not find the '=' sign */
	   
    INJECT_OPTION(key, "dsn"            , val, &(options->conninfo)  );
    INJECT_OPTION(key, "lookup_query"   , val, &(options->lookup)    );
    INJECT_OPTION(key, "getattr_query"  , val, &(options->getattr)   );
    INJECT_OPTION(key, "readdir_query"  , val, &(options->readdir)   );
    INJECT_OPTION(key, "file_info"      , val, &(options->file_info) );
    INJECT_OPTION(key, "statfs"         , val, &(options->statfs)    );
    INJECT_OPTION(key, "getxattr"       , val, &(options->getxattr)  );

    /* TODO: the DB pool size */

  }

  if(line) free(line);
  return 0;
}

int
ega_dist_loadconfig(struct ega_config* options)
{

  if(options->conf_fd < 0)
    return 1;

  D1("Loading configuration from fd %d", options->conf_fd);

  /* Read from the file descriptor */
  size_t size = 4096;
  FILE* fp = fdopen(options->conf_fd, "r");
  if (fp == NULL || errno == EACCES) {
    D2("Error accessing the config file: %s", strerror(errno));
    return 2;
  }

  options->buffer = NULL;
  int rc = 1;

REALLOC:
  D3("Allocating buffer of size %zd", size);
  if(options->buffer) free(options->buffer);
  options->buffer = malloc(sizeof(char) * size);
  if(!options->buffer) { D3("Could not allocate buffer"); rc = 3; goto bailout; };
  memset(options->buffer, '\0', size);
  /* *(options->buffer) = '\0'; */
  if(!options->buffer){ D3("Could not allocate buffer of size %zd", size); rc = 4; goto bailout; };

  if( readconfig(fp, options, options->buffer, size) < 0 ){

    /* Rewind first */
    if(fseek(fp, 0, SEEK_SET)){ D3("Could not rewind config file to start"); rc = 5; goto bailout; };

    /* Doubling the buffer size */
    size = size << 1;
    goto REALLOC;
  }

  D3("Conf loaded [@ %p]", options);

  rc = valid_options(options);

bailout:
  if(fp) fclose(fp);
  return rc;
}



/*
 * Moves a string value to a buffer (including a \0 at the end).
 * Adjusts the pointer to pointer right after the \0.
 *
 * Returns -size in case the buffer is <size> too small.
 * Otherwise, returns the <size> of the string (+1).
 */
static inline int
copy2buffer(const char* data, char** dest, char **bufptr, size_t *buflen)
{
  size_t dlen = strlen(data);

  if(*buflen < dlen + 1) {
    D3("buffer too small [currently: %zd bytes left] to copy \"%s\" [needs %zd +1 bytes]", *buflen, data, dlen);
    if(dest) *dest = NULL;
    return -dlen - 1;
  }

  /* strncpy(*bufptr, data, slen-1); */
  /* (*bufptr)[slen-1] = '\0'; */
  /* https://developers.redhat.com/blog/2018/05/24/detecting-string-truncation-with-gcc-8/ */

  /* record location */
  char* p = *bufptr;
  if(dest) *dest = p; 

  int i=0;
  for (; i < dlen && data[i] != '\0'; i++) /* whichever comes first */
    p[i] = data[i];
  p[i] = '\0';

  *bufptr += i + 1;
  *buflen -= i + 1;
  
  return i + 1;
}
