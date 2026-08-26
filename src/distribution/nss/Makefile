#
# Makefile for the NSS modules for EGA NSS cache
#

NSS_LD_SONAME = -Wl,-soname,libnss_egafiles.so.2
NSS_LIBRARY = libnss_egafiles.so.2.0
NSS_ARCHIVE = libnss_egafiles.a

EGA_LIBDIR = /opt/LocalEGA/lib

DEFINES+=-DEGAFILES_USERS_PATH=\"/opt/LocalEGA/etc/nss/users\"
DEFINES+=-DEGAFILES_GROUPS_PATH=\"/opt/LocalEGA/etc/nss/groups\"
DEFINES+=-DEGAFILES_PASSWORDS_PATH=\"/opt/LocalEGA/etc/nss/passwords\"

CC=gcc
LD=ld
AS=gcc -c
AR=ar
RANLIB=ranlib
CFLAGS=-O2 -Wall -Wstrict-prototypes -Werror -fPIC -I. $(DEFINES)

NSS_OBJECTS = nss.o

.PHONY: all clean install
.SUFFIXES: .c .o .S .so .so.2 .so.2.0

all: $(NSS_LIBRARY)


$(EGA_LIBDIR):
	@echo "Creating lib dir: $(EGA_LIBDIR)"
	@install -d $(EGA_LIBDIR)

$(NSS_LIBRARY): $(NSS_OBJECTS)
	@echo "Linking objects into $@"
	@$(CC) -shared $(NSS_LD_SONAME) -o $@ $(NSS_OBJECTS) -lpthread

$(NSS_ARCHIVE): $(NSS_OBJECTS)
	@echo "Archiving objects into $@"
	$(AR) rv $@ $(NSS_OBJECTS)
	$(RANLIB) $@


%.o: %.c
	@echo "Compiling $<"
	@$(CC) $(CFLAGS) -c -o $@ $<

install-a: $(NSS_ARCHIVE) | $(EGA_LIBDIR)
	@echo "Installing $< into $(EGA_LIBDIR)"
	@install $< $(EGA_LIBDIR)

install-so: $(NSS_LIBRARY) | $(EGA_LIBDIR)
	@echo "Installing $< into $(EGA_LIBDIR)"
	@install $< $(EGA_LIBDIR)

install: install-so #install-a

debug1: CFLAGS += -DDEBUG=1
debug1: install
debug2: CFLAGS += -DDEBUG=2
debug2: install
debug3: CFLAGS += -DDEBUG=3
debug3: install

clean:
	-rm -f $(NSS_LIBRARY) $(NSS_OBJECTS) $(NSS_ARCHIVE)
