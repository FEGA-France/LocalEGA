#ifndef __EGA_DIST_DEBUG_H_INCLUDED__
#define __EGA_DIST_DEBUG_H_INCLUDED__ 1

#include <stdlib.h>
#include <stddef.h>
#include <unistd.h>

#include <string.h>
#include <stdio.h>

#ifndef DEBUG
#error "You must define a debug level"
#endif

/* Ignore the logs */
#define __EGA_DIST_LOG_H_INCLUDED__ 1

#define DEBUG_FUNC(level, fmt, ...) fprintf(stderr, "%-10s(%3d) |" level " " fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__)

#define E(fmt, ...) DEBUG_FUNC("ERROR", fmt, ##__VA_ARGS__)

#if DEBUG > 0
#define D1(fmt, ...) DEBUG_FUNC("", fmt, ##__VA_ARGS__)
#else
#define D1(...)
#endif

#if DEBUG > 1
#define D2(fmt, ...) DEBUG_FUNC("    ", fmt, ##__VA_ARGS__)
#else
#define D2(...)
#endif

#if DEBUG > 2
#define D3(fmt, ...) DEBUG_FUNC("        ", fmt, ##__VA_ARGS__)
#else
#define D3(...)
#endif


#endif /* !__EGA_DIST_DEBUG_H_INCLUDED__ */
