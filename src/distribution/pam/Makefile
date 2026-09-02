# on Centos
# EGA_PAMDIR=/lib64/security
# on Debian
EGA_PAMDIR=/lib/x86_64-linux-gnu/security

all install clean:
	@make -C pam_ega_auth $@ EGA_PAMDIR=$(EGA_PAMDIR)
	@make -C pam_ega_homedir $@ EGA_PAMDIR=$(EGA_PAMDIR)
	@make -C pam_ega_localnss $@ EGA_PAMDIR=$(EGA_PAMDIR)
	@make -C pam_ega_mount $@ EGA_PAMDIR=$(EGA_PAMDIR)

debug1 debug2 debug3:
	make clean install DEBUG=$(@:debug%=%)
