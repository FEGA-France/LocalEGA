#ifndef __EGA_DIST_READCONF_H_INCLUDED__
#define __EGA_DIST_READCONF_H_INCLUDED__ 1

#include "fs.h"

int ega_dist_loadconfig(struct ega_config* options);
void ega_dist_cleanconfig(struct ega_config* options);

#endif /* !__EGA_DIST_READCONF_H_INCLUDED__ */
