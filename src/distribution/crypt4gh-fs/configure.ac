# -*- Autoconf -*-
# Process this file with autoconf to produce a configure script.

AC_PREREQ([2.71])
AC_INIT([ega-dist-fs],[1.0],[frederic.haziza@crg.eu])

AC_CONFIG_SRCDIR([main.c])
AC_CONFIG_HEADERS([config.h])

AC_LANG([C])

AC_PROG_CC([cc gcc])
AC_PROG_CC #([cc clang gcc])
AC_PROG_CPP
AC_CHECK_TOOL([PKG_CONFIG], [pkg-config])

AC_C_INLINE
# AC_C_BIGENDIAN

# First of all, we need libsodium
AC_SEARCH_LIBS([fuse_session_mount], [fuse3], [
			      CFLAGS="${CFLAGS} $(${PKG_CONFIG} --cflags fuse3)"
			      LDFLAGS="$LDFLAGS $(${PKG_CONFIG} --libs fuse3)"
				     ],
		[AC_MSG_ERROR("fuse3 is required. Install it from https://github.com/libfuse/libfuse.")])
AC_SEARCH_LIBS([PQconnectdb], [pq], [
			      CFLAGS="${CFLAGS} $(${PKG_CONFIG} --cflags libpq)"
			      LDFLAGS="$LDFLAGS $(${PKG_CONFIG} --libs libpq)"
			      ],
		[AC_MSG_ERROR("libpq is required. Install it from https://www.postgresql.org/docs/current/libpq.html.")])

AC_SEARCH_LIBS([pthread_mutex_lock], [pthread], [],
		[AC_MSG_ERROR("pthread is required")])


AC_SEARCH_LIBS([g_hash_table_new_full], [glib-2.0], [],
				[AC_MSG_ERROR("glib2.0 is required. Install it from https://docs.gtk.org/glib/.")])
CFLAGS="${CFLAGS} $(pkg-config --cflags glib-2.0)"
LDFLAGS="$LDFLAGS $(pkg-config --libs glib-2.0)"

if test "$GCC" = "yes"; then
   AC_MSG_CHECKING([if $CC accepts -fno-builtin-memset])
   saved_CFLAGS="$CFLAGS"
   CFLAGS="$CFLAGS -fno-builtin-memset"
   AC_LINK_IFELSE([AC_LANG_PROGRAM([[ #include <string.h> ]],
		[[ char b[10]; memset(b, 0, sizeof(b)); ]])],
	[ AC_MSG_RESULT([yes]) ],
	[ AC_MSG_RESULT([no])
	  CFLAGS="$saved_CFLAGS" ]
	)
fi

#######################################################

# Miscellaneous checks
AC_CACHE_CHECK([whether $CC implements __FUNCTION__], ac_cv_cc_implements___FUNCTION__, [
	AC_LINK_IFELSE([AC_LANG_PROGRAM([[ #include <stdio.h> ]],
		[[ printf("%s", __FUNCTION__); ]])],
	[ ac_cv_cc_implements___FUNCTION__="yes" ],
	[ ac_cv_cc_implements___FUNCTION__="no"
	])
])
if test "x$ac_cv_cc_implements___FUNCTION__" = "xyes" ; then
	AC_DEFINE([HAVE___FUNCTION__], [1],
		[Define if compiler implements __FUNCTION__])
fi

#######################################################

dnl AC_MSG_CHECKING([if compiler allows __attribute__ on return types])
dnl AC_COMPILE_IFELSE(
dnl     [AC_LANG_PROGRAM([[
dnl #include <stdlib.h>
dnl __attribute__((__unused__)) static void foo(void){return;}]],
dnl     [[ exit(0); ]])],
dnl     [ AC_MSG_RESULT([yes]) ],
dnl     [ AC_MSG_RESULT([no])
dnl       AC_DEFINE(NO_ATTRIBUTE_ON_RETURN_TYPE, 1,
dnl 	 [compiler does not accept __attribute__ on return types]) ]
dnl )

AC_MSG_CHECKING([if compiler allows __attribute__((nonnull)) on prototype args])
AC_COMPILE_IFELSE(
    [AC_LANG_PROGRAM([[
#include <stdlib.h>
static void foo(void* arg1, void* ) __attribute__((nonnull)) {return;}]],
    [[ exit(0); ]])],
    [ AC_MSG_RESULT([yes]) ],
    [ AC_MSG_RESULT([no])
      AC_DEFINE(NO_ATTRIBUTE_ON_PROTOTYPE_ARGS, 1,
	 [compiler does not accept __attribute__((nonnull)) on prototype args]) ]
)

if test "x$no_attrib_nonnull" != "x1" ; then
	AC_DEFINE([HAVE_ATTRIBUTE__NONNULL__], [1], [Have attribute nonnull])
fi

#######################################################

# Checks for header files.
AC_CHECK_HEADERS([ \
	syslog.h \
])

# Checks for library functions.
AC_CHECK_FUNCS([ \
	strerror \
])

#######################################################

# Check for  long long datatypes
AC_TYPE_OFF_T

AC_CHECK_SIZEOF([int])

# More checks for data types
AC_CACHE_CHECK([for uintXX_t types], ac_cv_have_uintxx_t, [
		AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[
#include <sys/types.h>
			]], [[
	uint8_t a;
	uint32_t c;
	a = b = c = 1;
			]])],
		[ ac_cv_have_uintxx_t="yes" ], [ ac_cv_have_uintxx_t="no"
		])
	])
if test "x$ac_cv_have_uintxx_t" = "xyes" ; then
	AC_DEFINE([HAVE_UINTXX_T], [1],
		[define if you have uintxx_t data type])
fi

if (test -z "$have_uintxx_t" && \
	   test "x$ac_cv_header_stdint_h" = "xyes")
then
    AC_MSG_CHECKING([for uintXX_t types in stdint.h])
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <stdint.h> ]],
	[[ uint8_t a; uint32_t b; a = b = 1;]])],
		[
			AC_DEFINE([HAVE_UINTXX_T])
			AC_MSG_RESULT([yes])
		], [ AC_MSG_RESULT([no])
	])
fi

AC_CACHE_CHECK([for size_t], ac_cv_have_size_t, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/types.h> ]],
	[[ size_t foo; foo = 1235; ]])],
	[ ac_cv_have_size_t="yes" ], [ ac_cv_have_size_t="no"
	])
])
if test "x$ac_cv_have_size_t" = "xyes" ; then
	AC_DEFINE([HAVE_SIZE_T], [1], [define if you have size_t data type])
fi

#######################################################

debug_flag=no
AC_ARG_WITH([debug],
	[  --with-debug            Build main code with -g -DDEBUG=xxx],
	[
		if test -n "$withval"  &&  test "x$withval" != "xno"; then
			DEBUG="-DDEBUG=${withval}"
			debug_flag=yes
		fi
	]
)
AC_ARG_WITH([debug-prefix],
	[  --with-debug-prefix            Use prefix in debug statements],
	[
		if "x${debug_flag}" = "xyes" && test -n "$withval" ; then
			DEBUG="${DEBUG} -DDEBUG_PREFIX=${withval}"
		fi
	]
)


#######################################################

AC_SUBST([DEBUG], [$DEBUG])
AC_SUBST([DEPEND], [$(cat $srcdir/.depend)])

AC_CONFIG_FILES([Makefile])

AC_OUTPUT

if test "x$debug_flag" != "xno"; then
   # Print summary of options
   echo ""
   echo "            Compiler: ${CC}"
   echo "      Compiler flags: ${CFLAGS}"
   echo "  Preprocessor flags: ${CPPFLAGS}"
   echo "         Definitions: ${DEFS} $DEBUG"
   echo "        Linker flags: ${LDLAGS}"
   echo "                LIBS: ${LIBS}"
   echo ""
fi
