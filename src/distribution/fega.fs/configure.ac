# -*- Autoconf -*-
# Process this file with autoconf to produce a configure script.

AC_PREREQ([2.69])
AC_INIT([crypt4gh-sqlite-fs],[2.0],[silverdaz@gmail.com])

AC_CONFIG_SRCDIR([src/main.c])
AC_CONFIG_HEADERS([src/config.h])

# Store the auxiliary build tools (e.g., install-sh, config.sub, config.guess) in this dir (build-aux)
#AC_CONFIG_AUX_DIR([build-aux])

AC_LANG([C])

AC_PROG_CC([gcc cc])
AC_PROG_CPP
#AC_PROG_INSTALL
AC_PROG_AWK
AC_CHECK_TOOL([PKG_CONFIG], [pkg-config])
AC_PROG_RANLIB
AC_CHECK_TOOL([AR], [ar])

# System features
if test -z "$AR" ; then
   AC_MSG_ERROR([*** 'ar' missing, please install or fix your \$PATH ***])
fi

AC_C_INLINE
# AC_C_BIGENDIAN


# First of all, we need libsodium, for ssh-ed25519 keys, and libfuse
dnl old_CFLAGS="${CFLAGS}"
dnl old_LDFLAGS="$LDFLAGS"
CFLAGS="${CFLAGS} $(pkg-config --cflags libsodium fuse3 libcap)"
LDFLAGS="$LDFLAGS $(pkg-config --libs libsodium fuse3 libcap)"

AC_SEARCH_LIBS([sodium_malloc], [sodium], [],
				[AC_MSG_ERROR("libsodium is required. Install it from https://libsodium.org/.")])

AC_SEARCH_LIBS([fuse_lib_help], [fuse3], [],
				[AC_MSG_ERROR("fuse3 is required. Install it from https://github.com/libfuse/libfuse.")])

AC_SEARCH_LIBS([cap_init], [cap], [],
				[AC_MSG_ERROR("libcap is required. Install it, eg, apt install libcap-dev.")])

AC_SEARCH_LIBS([pthread_mutex_lock], [pthread], [],
				[AC_MSG_ERROR("pthread is required")])

dnl CFLAGS="${old_CFLAGS} $(pkg-config --cflags libsodium fuse3 libcap)"
dnl LDFLAGS="${old_LDFLAGS} $(pkg-config --libs libsodium fuse3 libcap)"


#######################################################
# GCC
#######################################################

if test "$GCC" = "yes"; then
	AC_MSG_CHECKING([gcc version])
	GCC_VER=`$CC -v 2>&1 | $AWK '/gcc version /{print $3}'`
	case $GCC_VER in
		1.*) no_attrib_nonnull=1 ;;
		2.8* | 2.9*)
		     no_attrib_nonnull=1
		     ;;
		2.*) no_attrib_nonnull=1 ;;
		*) ;;
	esac
	AC_MSG_RESULT([$GCC_VER])

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
# Enforce use of OpenSSL
AC_DEFINE_UNQUOTED([WITH_OPENSSL], [1], [use libcrypto for cryptography])

# Search for OpenSSL
openssl_found=false
AC_ARG_WITH([openssl], [AS_HELP_STRING([--with-openssl=DIR], [root of the OpenSSL directory])],
        [
         case "$withval" in
            "" | y | ye | yes | n | no) AC_MSG_ERROR([Invalid --with-openssl value]);;
            *) ssldirs="$withval";;
         esac
        ], [
            # if pkg-config is installed and openssl has installed a .pc file,
            # then use that information and don't search ssldirs
            if test -z "$PKG_CONFIG"; then
                OPENSSL_LDFLAGS=`$PKG_CONFIG openssl --libs-only-L 2>/dev/null`
                if test $? = 0; then
                    OPENSSL_LIBS=`$PKG_CONFIG openssl --libs-only-l 2>/dev/null`
                    OPENSSL_INCLUDES=`$PKG_CONFIG openssl --cflags-only-I 2>/dev/null`
                    openssl_found=true
                fi
            fi

            # no such luck; use some default ssldirs
            if ! $openssl_found; then
                ssldirs="/usr/local/ssl /usr/lib/ssl /usr/ssl /usr/pkg /usr/local /usr"
            fi
        ]
)

# note that we #include <openssl/foo.h>, so the OpenSSL headers have to be in
# an 'openssl' subdirectory

if ! $openssl_found; then
   OPENSSL_INCLUDES=
   for ssldir in $ssldirs; do
       AC_MSG_CHECKING([for include/openssl/ssl.h in $ssldir])
       if test -f "$ssldir/include/openssl/ssl.h"; then
           OPENSSL_INCLUDES="-I$ssldir/include"
           OPENSSL_LDFLAGS="-L$ssldir/lib"
           OPENSSL_LIBS="-lssl -lcrypto"
           openssl_found=yes
           AC_MSG_RESULT([yes])
           break
       else
           AC_MSG_RESULT([no])
       fi
   done

   # if the file wasn't found, well, go ahead and try the link anyway -- maybe
   # it will just work!
fi

# try the preprocessor and linker with our new flags,
# being careful not to pollute the global LIBS, LDFLAGS, and CPPFLAGS

AC_MSG_CHECKING([whether compiling and linking against OpenSSL works])

echo "Trying link with OPENSSL_LDFLAGS=$OPENSSL_LDFLAGS;" \
     "OPENSSL_LIBS=$OPENSSL_LIBS; OPENSSL_INCLUDES=$OPENSSL_INCLUDES" >&AS_MESSAGE_LOG_FD

LDFLAGS="$LDFLAGS $OPENSSL_LDFLAGS"
LIBS="$OPENSSL_LIBS $LIBS"
CPPFLAGS="$OPENSSL_INCLUDES $CPPFLAGS"
AC_LINK_IFELSE(
    [AC_LANG_PROGRAM([#include <openssl/ssl.h>], [SSL_new(NULL)])],
    [AC_MSG_RESULT([yes])],
    [ AC_MSG_RESULT([no])
      AC_MSG_ERROR([OpenSSL distribution not found])
    ])

#LIBS="-lssl -lcrypto $LIBS"
#LIBS="$LIBS $($PKG_CONFIG --libs openssl)"

# Determine OpenSSL library version
AC_MSG_CHECKING([OpenSSL library version])
AC_RUN_IFELSE(
	[AC_LANG_PROGRAM([[
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/opensslv.h>
#include <openssl/crypto.h>
#define DATA "conftest.ssllibver"
	]], [[
		FILE *fd;
		int rc;

		fd = fopen(DATA,"w");
		if(fd == NULL)
			exit(1);
		if ((rc = fprintf(fd, "%08lx (%s)\n",
		    (unsigned long)OpenSSL_version_num(),
		    OpenSSL_version(OPENSSL_VERSION))) < 0)
			exit(1);

		exit(0);
	]])],
	[
		ssl_library_ver=`cat conftest.ssllibver`
		# Check version is supported.
		case "$ssl_library_ver" in
			101*)   ;; # 1.1.x
			200*)   ;; # LibreSSL
			3*)   ;; # OpenSSL 3.x
		        *)
				AC_MSG_ERROR([OpenSSL >= 3.x required (have "$ssl_library_ver")])
		                ;;
		esac
		AC_MSG_RESULT([$ssl_library_ver])
	],
	[
		AC_MSG_RESULT([not found])
		AC_MSG_ERROR([OpenSSL library not found.])
	],
	[
		AC_MSG_WARN([cross compiling: not checking])
	]
)

# Print OpenSSL version
AC_MSG_CHECKING([OpenSSL version])
AC_RUN_IFELSE(
	[AC_LANG_PROGRAM([[
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <openssl/opensslv.h>
#include <openssl/crypto.h>
	]], [[
	FILE *fd;
	int rc = 0;
	fd = fopen("conftest.openssl.version","w");
	if(fd == NULL) exit(1);
	rc = fprintf(fd, "%s\n", OpenSSL_version(OPENSSL_VERSION));
	fclose(fd);
	exit((rc < 0)?rc:0);
	]])],
	[
		openssl_version=`cat conftest.openssl.version`
		AC_MSG_RESULT([$openssl_version])
	],
	[
		AC_MSG_RESULT([not found])
		AC_MSG_ERROR([OpenSSL version header not found.])
	],
	[
		AC_MSG_WARN([cross compiling: not checking])
	]
)

#######################################################
# Miscellaneous checks
#######################################################

AC_MSG_CHECKING([if compiler allows __attribute__ on return types])
AC_COMPILE_IFELSE(
    [AC_LANG_PROGRAM([[
#include <stdlib.h>
__attribute__((__unused__)) static void foo(void){return;}]],
    [[ exit(0); ]])],
    [ AC_MSG_RESULT([yes]) ],
    [ AC_MSG_RESULT([no])
      AC_DEFINE(NO_ATTRIBUTE_ON_RETURN_TYPE, 1,
	 [compiler does not accept __attribute__ on return types]) ]
)

AC_MSG_CHECKING([if compiler allows __attribute__ prototype args])
AC_COMPILE_IFELSE(
    [AC_LANG_PROGRAM([[
#include <stdlib.h>
typedef void foo(const char *, ...) __attribute__((format(printf, 1, 2)));]],
    [[ exit(0); ]])],
    [ AC_MSG_RESULT([yes]) ],
    [ AC_MSG_RESULT([no])
      AC_DEFINE(NO_ATTRIBUTE_ON_PROTOTYPE_ARGS, 1,
	 [compiler does not accept __attribute__ on prototype args]) ]
)

if test "x$no_attrib_nonnull" != "x1" ; then
	AC_DEFINE([HAVE_ATTRIBUTE__NONNULL__], [1], [Have attribute nonnull])
fi


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

AC_CACHE_CHECK([whether $CC implements __func__], ac_cv_cc_implements___func__, [
	AC_LINK_IFELSE([AC_LANG_PROGRAM([[ #include <stdio.h> ]],
		[[ printf("%s", __func__); ]])],
	[ ac_cv_cc_implements___func__="yes" ],
	[ ac_cv_cc_implements___func__="no"
	])
])
if test "x$ac_cv_cc_implements___func__" = "xyes" ; then
	AC_DEFINE([HAVE___func__], [1], [Define if compiler implements __func__])
fi


#######################################################

AC_CHECK_HEADERS([ \
	blf.h \
	crypt.h \
	crypto/sha2.h \
	endian.h \
	features.h \
	fcntl.h \
	limits.h \
	sha2.h \
	stddef.h \
	stdint.h \
	string.h \
	strings.h \
	sys/byteorder.h \
	sys/stat.h \
	unistd.h \
	readpassphrase.h \
	pwd.h \
	grp.h \
])

# Check for Endianness
AC_C_BIGENDIAN(
  AC_DEFINE(NATIVE_BIG_ENDIAN, 1, [machine is big-endian]),
  AC_DEFINE(NATIVE_LITTLE_ENDIAN, 1, [machine is little-endian]),
  AC_MSG_ERROR([unknown endianness]),
  AC_MSG_ERROR([universal endianness is not supported - compile separately and use lipo(1)])
)

# "Particular Function Checks"
# see https://www.gnu.org/software/autoconf/manual/autoconf-2.69/html_node/Particular-Functions.html
AC_FUNC_MEMCMP
AC_FUNC_LSTAT
AC_FUNC_MALLOC
AC_FUNC_REALLOC
# autoconf doesn't have AC_FUNC_CALLOC so fake it if malloc returns NULL;
AC_MSG_CHECKING([if calloc(0, N) returns non-null])
AC_RUN_IFELSE(
	[AC_LANG_PROGRAM(
		[[ #include <stdlib.h> ]],
		[[ void *p = calloc(0, 1); exit(p == NULL); ]]
	)],
	[ func_calloc_0_nonnull=yes ],
	[ func_calloc_0_nonnull=no ],
	[ AC_MSG_WARN([cross compiling: assuming same as malloc])
	  func_calloc_0_nonnull="$ac_cv_func_malloc_0_nonnull"]
)
AC_MSG_RESULT([$func_calloc_0_nonnull])

if test "x$func_calloc_0_nonnull" = "xyes"; then
	AC_DEFINE(HAVE_CALLOC, 1, [calloc(0, x) returns non-null])
else
	AC_DEFINE(HAVE_CALLOC, 0, [calloc(0, x) returns NULL])
	AC_DEFINE(calloc, rpl_calloc,
	    [Define to rpl_calloc if the replacement function should be used.])
fi

# Checks for library functions. Please keep in alphabetical order
AC_CHECK_FUNCS([ \
	Blowfish_initstate \
	Blowfish_expandstate \
	Blowfish_expand0state \
	Blowfish_stream2word \
	SHA256Update \
	SHA384Update \
	SHA512Update \
	b64_ntop \
	b64_pton \
	bcrypt_pbkdf \
	blf_enc \
	bzero \
	explicit_bzero \
	freezero \
	memset_s \
	strdup \
	strerror \
	statx \
])

	# memmem \
	# memmove \
	#__b64_pton \
	#__b64_ntop \

#######################################################
# OpenSSL funcs
###################################################

AC_CHECK_FUNCS([ \
	OPENSSL_init_crypto \
        PKCS5_PBKDF2_HMAC \
	EVP_MD_CTX_new \
	EVP_MD_CTX_free \
	EVP_sha256 \
])

#######################################################
# Type checks
#######################################################

# Check for  long long datatypes
AC_TYPE_OFF_T

#Check datatype sizes
AC_CHECK_SIZEOF([int])

# More checks for data types
AC_CACHE_CHECK([for uintXX_t types], ac_cv_have_uintxx_t, [
		AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[
#include <sys/types.h>
			]], [[
	uint8_t a;
	uint32_t b;
	uint64_t c;
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
	[[ uint8_t a; uint32_t b; uint64_t c; a = b = c = 1;]])],
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

#########################################

# Check for  long long datatypes
AC_CHECK_TYPES([long long, unsigned long long, long double])

# Check datatype sizes
AC_CHECK_SIZEOF([short int])
AC_CHECK_SIZEOF([int])
AC_CHECK_SIZEOF([long int])
AC_CHECK_SIZEOF([long long int])

AC_CHECK_DECLS([UINT32_MAX], , , [[
#ifdef HAVE_SYS_LIMITS_H
# include <sys/limits.h>
#endif
#ifdef HAVE_LIMITS_H
# include <limits.h>
#endif
#ifdef HAVE_STDINT_H
# include <stdint.h>
#endif
]])

# More checks for data types
AC_CACHE_CHECK([for u_int type], ac_cv_have_u_int, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/types.h> ]],
	[[ u_int a; a = 1;]])],
	[ ac_cv_have_u_int="yes" ], [ ac_cv_have_u_int="no"
	])
])
if test "x$ac_cv_have_u_int" = "xyes" ; then
	AC_DEFINE([HAVE_U_INT], [1], [define if you have u_int data type])
	have_u_int=1
fi

AC_CACHE_CHECK([for intXX_t types], ac_cv_have_intxx_t, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/types.h> ]],
	[[ int8_t a; int16_t b; int32_t c; a = b = c = 1;]])],
	[ ac_cv_have_intxx_t="yes" ], [ ac_cv_have_intxx_t="no"
	])
])
if test "x$ac_cv_have_intxx_t" = "xyes" ; then
	AC_DEFINE([HAVE_INTXX_T], [1], [define if you have intxx_t data type])
	have_intxx_t=1
fi

if (test -z "$have_intxx_t" && \
	   test "x$ac_cv_header_stdint_h" = "xyes")
then
    AC_MSG_CHECKING([for intXX_t types in stdint.h])
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <stdint.h> ]],
	[[ int8_t a; int16_t b; int32_t c; a = b = c = 1;]])],
		[
			AC_DEFINE([HAVE_INTXX_T])
			AC_MSG_RESULT([yes])
		], [ AC_MSG_RESULT([no])
	])
fi

AC_CACHE_CHECK([for int64_t type], ac_cv_have_int64_t, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[
#include <sys/types.h>
#ifdef HAVE_STDINT_H
# include <stdint.h>
#endif
#include <sys/socket.h>
#ifdef HAVE_SYS_BITYPES_H
# include <sys/bitypes.h>
#endif
		]], [[
int64_t a; a = 1;
		]])],
	[ ac_cv_have_int64_t="yes" ], [ ac_cv_have_int64_t="no"
	])
])
if test "x$ac_cv_have_int64_t" = "xyes" ; then
	AC_DEFINE([HAVE_INT64_T], [1], [define if you have int64_t data type])
fi

AC_CACHE_CHECK([for u_intXX_t types], ac_cv_have_u_intxx_t, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/types.h> ]],
	[[ u_int8_t a; u_int16_t b; u_int32_t c; a = b = c = 1;]])],
	[ ac_cv_have_u_intxx_t="yes" ], [ ac_cv_have_u_intxx_t="no"
	])
])
if test "x$ac_cv_have_u_intxx_t" = "xyes" ; then
	AC_DEFINE([HAVE_U_INTXX_T], [1], [define if you have u_intxx_t data type])
	have_u_intxx_t=1
fi

if test -z "$have_u_intxx_t" ; then
    AC_MSG_CHECKING([for u_intXX_t types in sys/socket.h])
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/socket.h> ]],
	[[ u_int8_t a; u_int16_t b; u_int32_t c; a = b = c = 1;]])],
		[
			AC_DEFINE([HAVE_U_INTXX_T])
			AC_MSG_RESULT([yes])
		], [ AC_MSG_RESULT([no])
	])
fi

AC_CACHE_CHECK([for u_int64_t types], ac_cv_have_u_int64_t, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/types.h> ]],
	[[ u_int64_t a; a = 1;]])],
	[ ac_cv_have_u_int64_t="yes" ], [ ac_cv_have_u_int64_t="no"
	])
])
if test "x$ac_cv_have_u_int64_t" = "xyes" ; then
	AC_DEFINE([HAVE_U_INT64_T], [1], [define if you have u_int64_t data type])
	have_u_int64_t=1
fi

if (test -z "$have_u_int64_t" && \
	   test "x$ac_cv_header_sys_bitypes_h" = "xyes")
then
    AC_MSG_CHECKING([for u_int64_t type in sys/bitypes.h])
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/bitypes.h> ]],
	[[ u_int64_t a; a = 1]])],
		[
			AC_DEFINE([HAVE_U_INT64_T])
			AC_MSG_RESULT([yes])
		], [ AC_MSG_RESULT([no])
	])
fi

if test -z "$have_u_intxx_t" ; then
	AC_CACHE_CHECK([for uintXX_t types], ac_cv_have_uintxx_t, [
		AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[
#include <sys/types.h>
			]], [[
	uint8_t a;
	uint16_t b;
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
fi

if (test -z "$have_uintxx_t" && \
	   test "x$ac_cv_header_stdint_h" = "xyes")
then
    AC_MSG_CHECKING([for uintXX_t types in stdint.h])
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <stdint.h> ]],
	[[ uint8_t a; uint16_t b; uint32_t c; a = b = c = 1;]])],
		[
			AC_DEFINE([HAVE_UINTXX_T])
			AC_MSG_RESULT([yes])
		], [ AC_MSG_RESULT([no])
	])
fi

if (test -z "$have_uintxx_t" && \
	   test "x$ac_cv_header_inttypes_h" = "xyes")
then
    AC_MSG_CHECKING([for uintXX_t types in inttypes.h])
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <inttypes.h> ]],
	[[ uint8_t a; uint16_t b; uint32_t c; a = b = c = 1;]])],
		[
			AC_DEFINE([HAVE_UINTXX_T])
			AC_MSG_RESULT([yes])
		], [ AC_MSG_RESULT([no])
	])
fi

if (test -z "$have_u_intxx_t" || test -z "$have_intxx_t" && \
	   test "x$ac_cv_header_sys_bitypes_h" = "xyes")
then
	AC_MSG_CHECKING([for intXX_t and u_intXX_t types in sys/bitypes.h])
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[
#include <sys/bitypes.h>
		]], [[
			int8_t a; int16_t b; int32_t c;
			u_int8_t e; u_int16_t f; u_int32_t g;
			a = b = c = e = f = g = 1;
		]])],
		[
			AC_DEFINE([HAVE_U_INTXX_T])
			AC_DEFINE([HAVE_INTXX_T])
			AC_MSG_RESULT([yes])
		], [AC_MSG_RESULT([no])
	])
fi


AC_CACHE_CHECK([for u_char], ac_cv_have_u_char, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/types.h> ]],
	[[ u_char foo; foo = 125; ]])],
	[ ac_cv_have_u_char="yes" ], [ ac_cv_have_u_char="no"
	])
])
if test "x$ac_cv_have_u_char" = "xyes" ; then
	AC_DEFINE([HAVE_U_CHAR], [1], [define if you have u_char data type])
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

AC_CACHE_CHECK([for ssize_t], ac_cv_have_ssize_t, [
	AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[ #include <sys/types.h> ]],
	[[ ssize_t foo; foo = 1235; ]])],
	[ ac_cv_have_ssize_t="yes" ], [ ac_cv_have_ssize_t="no"
	])
])
if test "x$ac_cv_have_ssize_t" = "xyes" ; then
	AC_DEFINE([HAVE_SSIZE_T], [1], [define if you have ssize_t data type])
fi


#######################################################
# Debug options
#######################################################

debug_flag=no
AC_ARG_WITH([debug],
	[  --with-debug		Build main code with -g -DDEBUG=xxx],
	[
		if test -n "$withval"  &&  test "x$withval" != "xno"; then
			DEBUG="-DDEBUG=${withval}"
			debug_flag=yes
		fi
	]
)
AC_ARG_WITH([debug-prefix],
	[  --with-debug-prefix		Use prefix in debug statements],
	[
		if "x${debug_flag}" = "xyes" && test -n "$withval" ; then
			DEBUG="${DEBUG} -DDEBUG_PREFIX=${withval}"
		fi
	]
)

syslog_flag=no
AC_ARG_WITH([syslog],
	[  --with-syslog		Build main code with -DHAVE_SYSLOG_H],
	[
		if test -n "$withval"  &&  test "x$withval" != "xno"; then
			AC_CHECK_HEADERS([syslog.h])
			syslog_flag=yes
		fi
	]
)
AC_ARG_WITH([syslog-level],
	[  --with-syslog-level		Use the given syslog level],
	[
		if "x${syslog_flag}" = "xyes" && test -n "$withval" ; then
			CPPFLAGS="${CPPFLAGS} -DHAVE_SYSLOG_LEVEL=${withval}"
		fi
	]
)



#######################################################

AC_CONFIG_FILES([Makefile])

AC_SUBST([DEPEND], [$(cat $srcdir/src/.depend)])
AC_SUBST([DEBUG], [$DEBUG])

AC_OUTPUT

#if test "x$debug_flag" != "xno"; then
   # Print summary of options
   echo ""
   echo "            Compiler: ${CC}"
   echo "      Compiler flags: ${CFLAGS}"
   echo "  Preprocessor flags: ${CPPFLAGS}"
   echo "         Definitions: ${DEFS} $DEBUG"
   echo "        Linker flags: ${LDFLAGS}"
   echo "                LIBS: ${LIBS}"
   echo ""
#fi

