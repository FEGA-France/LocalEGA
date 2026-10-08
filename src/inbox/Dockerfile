# based on debian:trixie-slim
FROM python:3.14-slim AS build

RUN apt-get update && \
#    apt-get upgrade && \
    apt-get install -y --no-install-recommends \
            vim ca-certificates pkg-config git gcc cmake make automake autoconf libtool patch \
            bzip2 zlib1g-dev libssl-dev libedit-dev procps \
            libpam0g-dev libreadline-dev xattr rsyslog

# For Python rescan.py
RUN pip install aiormq

ARG LEGA_UID=1000
ARG LEGA_GID=1000

RUN \
<<EOFPWD cat > /etc/passwd && \
<<EOFGRP cat > /etc/group && \
<<EOFSHADOW cat > /etc/shadow
root:x:0:0:root:/root:/bin/bash
# _apt:x:42:65534::/nonexistent:/usr/sbin/nologin
ega-sshd:x:$((LEGA_UID + 1)):$((LEGA_GID + 1)):Privilege-separated SSH:/var/empty/sshd:/usr/sbin/nologin
lega:x:${LEGA_UID}:${LEGA_GID}:Local EGA:/home/lega:/usr/sbin/nologin
EOFPWD
root:x:0:
shadow:x:1:
lega:x:${LEGA_GID}:lega
ega-sshd:x:$((LEGA_GID + 1)):ega-sshd
EOFGRP
root:*:19702:0:99999:7:::
# _apt:*:20564:0:99999:7:::
ega-sshd:*:19702:0:99999:7:::
lega:!:19702:0:99999:7:::
EOFSHADOW

# RUN groupadd -g $((LEGA_GID + 1)) ega-sshd
# RUN useradd -M -N -g $((LEGA_GID + 1)) -u $((LEGA_UID + 1)) -c 'Privilege-separated SSH' -d /var/empty/sshd -s /usr/sbin/nologin ega-sshd

# RUN groupadd -g ${LEGA_GID} lega
# RUN useradd -M -N -g ${LEGA_GID} -u ${LEGA_UID} -c 'Local EGA' -d /home/lega -s /usr/sbin/nologin lega

RUN chgrp shadow /etc/shadow && \
    chmod 640    /etc/shadow && \
# /var/empty/sshd must be owned by root and not group or world-writable.
    mkdir -p /var/empty/sshd   && \
    chmod 700 /var/empty/sshd  &&\
    mkdir -p /home/lega/.ssh   && \
    chmod -R 700 /home/lega    && \
    chown -R lega:lega /home/lega

COPY src/openssh /var/src/openssh
COPY src/patches /var/src/patches

######### OpenSSH
WORKDIR /var/src/openssh

# Patching the sftp-server.c
RUN patch -p1 < ../patches/lega.patch

# (re)Build OpenSSH
RUN autoreconf && \
    ./configure --prefix=/opt/openssh \
                --with-pam --with-pam-service=ega \
		--with-zlib \
		--with-openssl \
		--with-libedit \
		--with-privsep-user=ega-sshd \
	        --with-privsep-path=/var/empty/sshd \
	        --without-xauth \
 	        --without-maildir \
		--without-selinux \
		--without-systemd \
		--with-pid-dir=/run

RUN  make && \
# rsa, dsa and ed25519 keys are created in the entrypoint
     make install-nosysconf


#################################################
# for test

COPY conf/sshd_config /etc/ega/sshd_config
COPY conf/pam.ega /etc/pam.d/ega
COPY conf/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY conf/banner /etc/ega/banner

RUN chmod 755 /usr/local/bin/entrypoint.sh && \
    mkdir -p /etc/ega          && \
# for safe-chroot
    mkdir -p /ega/inbox        && \
    chown root:root /ega/inbox && \
    chmod 755 /ega/inbox       && \
# for the upload as lega:lega
    mkdir -m 700 /ega/inbox/home && \
    chown lega:lega /ega/inbox/home

VOLUME /ega/inbox/home
ENV FEGA_INBOX=/ega/inbox/home

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]


#################################################
##
## Final image
##
#################################################

FROM python:3.14-slim

LABEL maintainer="EGA System Developers"
LABEL org.label-schema.schema-version="1.0"
LABEL org.label-schema.vcs-url="https://github.com/FEGA-France/LocalEGA"

EXPOSE 9000
EXPOSE 15672
EXPOSE 5672

COPY --from=build /etc/passwd /etc/passwd
COPY --from=build /etc/shadow /etc/shadow
COPY --from=build /etc/group /etc/group

COPY --from=build --chown=lega:lega /home/lega       /home/lega
COPY --from=build /var/empty/sshd  /var/empty/sshd

# ARG ARCH=x86_64
# COPY --from=build /usr/lib/$ARCH-linux-gnu/ /usr/lib/$ARCH-linux-gnu/
COPY --from=build /usr/lib /usr/lib
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /usr/local/lib /usr/local/lib

# OpenSSH files
COPY --from=build /opt/openssh /opt/openssh

# Rsyslog files
COPY --from=build /usr/sbin/rsyslogd /usr/sbin/rsyslogd
COPY --from=build /etc/rsyslog.conf /etc/rsyslog.conf
COPY --from=build /etc/rsyslog.d /etc/rsyslog.d
COPY --from=build /var/spool/rsyslog /var/spool/rsyslog
# COPY --from=build /lib/$ARCH-linux-gnu/ /lib/$ARCH-linux-gnu/
# libz.so.1 => /lib/aarch64-linux-gnu/libz.so.1 (0x0000ffffb4700000)
# libm.so.6 => /lib/aarch64-linux-gnu/libm.so.6 (0x0000ffffb4650000)
# libestr.so.0 => /lib/aarch64-linux-gnu/libestr.so.0 (0x0000ffffb4620000)
# libfastjson.so.4 => /lib/aarch64-linux-gnu/libfastjson.so.4 (0x0000ffffb45f0000)
# libsystemd.so.0 => /lib/aarch64-linux-gnu/libsystemd.so.0 (0x0000ffffb44c0000)
# libuuid.so.1 => /lib/aarch64-linux-gnu/libuuid.so.1 (0x0000ffffb4490000)
# libcap.so.2 => /lib/aarch64-linux-gnu/libcap.so.2 (0x0000ffffb42a0000)


# Python rescan.py
COPY --from=build /usr/local/lib/python3.14/ /usr/local/lib/python3.14/
COPY --chmod=0755 src/rescan.py /usr/local/bin/ega-rescan

RUN chmod 755 /usr/local/bin/entrypoint.sh && \
    mkdir -p /etc/ega          && \
# for safe-chroot
    mkdir -p /ega/inbox        && \
    chown root:root /ega/inbox && \
    chmod 755 /ega/inbox       && \
# for the upload as lega:lega
    mkdir -m 700 /ega/inbox/home && \
    chown lega:lega /ega/inbox/home


COPY conf/sshd_config /etc/ega/sshd_config
COPY conf/pam.ega /etc/pam.d/ega
COPY conf/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY conf/banner /etc/ega/banner

VOLUME /ega/inbox/home
ENV FEGA_INBOX=/ega/inbox/home

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

ARG COMMIT
ARG BUILD_DATE
LABEL org.label-schema.build-date=$BUILD_DATE
LABEL org.label-schema.vcs-ref=$COMMIT
