#ifndef __EGA_DIST_LOG_H_INCLUDED__
#define __EGA_DIST_LOG_H_INCLUDED__ 1

#include <stdlib.h>
#include <stddef.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>

#define D1(...)
#define D2(...)
#define D3(...)
#define E(fmt, ...) fprintf(stderr, fmt "\n", ##__VA_ARGS__)

#endif /* !__EGA_DIST_LOG_H_INCLUDED__ */
