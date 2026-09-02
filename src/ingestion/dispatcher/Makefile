# The dispatcher doesn't write files to disk
# So, no need for specific LEGA_UID/LEGA_GID.
# However, it needs to read injected config files
# so we give it the current uid/gid

LEGA_UID=$(shell id -u)
LEGA_GID=$(shell id -g)

SERVICE=dispatcher

include ../docker.mk
