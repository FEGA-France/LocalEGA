#
# Makefile for the PAM auth module used in Federated EGA distribution
#
# Blowfish code from http://www.openwall.com/crypt/
#

PAM_MODULE = pam_ega_auth.so

# on Centos
# EGA_PAMDIR=/lib64/security
# on Debian
EGA_PAMDIR=/lib/x86_64-linux-gnu/security

# Or in general in here
#EGA_PAMDIR=/lib/security

CC=gcc
LD=ld
AS=gcc -c
CFLAGS=-O2 -pipe -Wstrict-prototypes \
	-Wall -Wpointer-arith -Wuninitialized \
	-Wsign-compare -Wformat-security -Wsizeof-pointer-memaccess -Wno-pointer-sign \
	-Wno-unused-result -fno-strict-aliasing \
	-fno-builtin-memset -fstack-protector-strong -fPIC
CPPFLAGS=-I. -I/usr/local/include
INSTALL=/usr/bin/install -c


ifndef NO_SYSLOG
CFLAGS += -DHAS_SYSLOG
endif

ifdef DEBUG
CFLAGS += -DDEBUG=$(DEBUG) -g
endif

HEADERS = utils.h blowfish/crypt_blowfish.h blowfish/crypt_gensalt.h
BFOBJS = blowfish/crypt_blowfish.o \
	 blowfish/crypt_gensalt.o \
	 blowfish/x86.o #blowfish/wrapper.o

.PHONY: all clean install
.SUFFIXES: .c .o .so .so.2 .so.2.0

all: $(PAM_MODULE)

$(EGA_PAMDIR):
	install -d $(EGA_PAMDIR)

$(PAM_MODULE): pam.o $(BFOBJS)
	$(LD) -x --shared -o $@ -lpam -lcrypt $^

%.o: %.c utils.h
	$(CC) $(CFLAGS) $(CPPFLAGS) -c $< -o $@

install: $(PAM_MODULE) | $(EGA_PAMDIR)
	$(INSTALL) -m 0644 $< $(EGA_PAMDIR)/$<

clean:
	-rm -f 	$(PAM_MODULE) *.o $(wildcard blowfish/*.o)

blowfish/x86.o: blowfish/x86.S $(HEADERS)
	$(AS) -o $@ $<
