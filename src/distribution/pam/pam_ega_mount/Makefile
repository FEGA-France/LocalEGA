#
# Makefile for the PAM mount module used in Federated EGA distribution
#

PAM_MODULE = pam_ega_mount.so

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

.PHONY: all clean install
.SUFFIXES: .c .o .so .so.2 .so.2.0

all: $(PAM_MODULE)

$(EGA_PAMDIR):
	install -d $(EGA_PAMDIR)

$(PAM_MODULE): pam.o
	$(LD) -x --shared -o $@ $< -lpam

%.o: %.c utils.h
	$(CC) $(CFLAGS) $(CPPFLAGS) -c $< -o $@

install: $(PAM_MODULE) | $(EGA_PAMDIR)
	$(INSTALL) -m 0644 $< $(EGA_PAMDIR)/$<

clean:
	-rm -f 	$(PAM_MODULE) *.o
