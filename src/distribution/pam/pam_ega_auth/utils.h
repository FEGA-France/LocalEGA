#ifndef __EGA_UTILS_H_INCLUDED__
#define __EGA_UTILS_H_INCLUDED__

#include <stdlib.h>
#include <stddef.h>
#include <unistd.h>

#define _XOPEN_SOURCE 700 /* for stpcpy */
#include <string.h>
#include <stdio.h>
#include <syslog.h>

#ifdef REPORT
#undef REPORT
#define REPORT(fmt, ...) fprintf(stderr, "[%d] "fmt"\n", getpid(), ##__VA_ARGS__)
#else
#undef REPORT
#define REPORT(...)
#endif

#define D1(...)
#define D2(...)
#define D3(...)

#ifdef DEBUG

extern char* syslog_name;

#ifdef HAS_SYSLOG
#define DEBUG_FUNC(level, fmt, ...) syslog(LOG_MAKEPRI(LOG_USER, LOG_ERR), level" "fmt"\n", ##__VA_ARGS__)
#define LEVEL1 "EGA pam:"
#define LEVEL2 "EGA pam:    "
#define LEVEL3 "EGA pam:        "
#else
#define DEBUG_FUNC(level, fmt, ...) fprintf(stderr, "[%5d / %5d] %-10s(%3d)%22s |" level " " fmt "\n", getppid(), getpid(), __FILE__, __LINE__, __FUNCTION__, ##__VA_ARGS__)
#define LEVEL1 ""
#define LEVEL2 "    "
#define LEVEL3 "        "
#endif

#if DEBUG > 0
#undef D1
#define D1(fmt, ...) DEBUG_FUNC(LEVEL1, fmt, ##__VA_ARGS__)
#endif

#if DEBUG > 1
#undef D2
#define D2(fmt, ...) DEBUG_FUNC(LEVEL2, fmt, ##__VA_ARGS__)
#endif

#if DEBUG > 2
#undef D3
#define D3(fmt, ...) DEBUG_FUNC(LEVEL3, fmt, ##__VA_ARGS__)
#endif

#endif /* !DEBUG */

#endif /* !__EGA_UTILS_H_INCLUDED__ */

