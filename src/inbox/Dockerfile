# based on debian:trixie-slim
FROM python:3.14-slim AS build

RUN apt-get update && \
#    apt-get upgrade && \
    apt-get install -y --no-install-recommends \
            vim ca-certificates pkg-config git gcc cmake make automake autoconf libtool patch \
            bzip2 zlib1g-dev libssl-dev libedit-dev procps \
            libjson-c-dev libpam0g-dev uuid-dev libreadline-dev librabbitmq-dev \
            gosu

# gosu working?
RUN gosu nobody true

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
rabbitmq:x:$((LEGA_UID + 2)):$((LEGA_GID + 2)):RabbitMQ:/var/lib/rabbitmq:/usr/sbin/nologin
EOFPWD
root:x:0:
shadow:x:1:
lega:x:${LEGA_GID}:lega
ega-sshd:x:$((LEGA_GID + 1)):ega-sshd
rabbitmq:x:$((LEGA_GID + 2)):rabbitmq
EOFGRP
root:*:19702:0:99999:7:::
# _apt:*:20564:0:99999:7:::
ega-sshd:*:19702:0:99999:7:::
rabbitmq:!:19702:0:99999:7:::
lega:!:19702:0:99999:7:::
EOFSHADOW

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
RUN cp ../patches/fega-mq.c .
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

COPY conf/entrypoint.sh /usr/local/bin/entrypoint.sh

# for test
RUN mkdir /etc/ega && \
    chmod 755 /usr/local/bin/entrypoint.sh

#################################################
## RabbitMQ
#################################################
FROM rabbitmq:4.2.6 AS rabbitmq

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

# Use the latest stable RabbitMQ release (https://www.rabbitmq.com/download.html)
ENV RABBITMQ_VERSION=4.2.6
# https://www.rabbitmq.com/signatures.html#importing-gpg
ENV RABBITMQ_HOME=/opt/rabbitmq
# Add RabbitMQ+Erlang to PATH
ENV PATH=$RABBITMQ_HOME/sbin:/opt/erlang/bin:$PATH

ENV LANG=C.UTF-8 LANGUAGE=C.UTF-8 LC_ALL=C.UTF-8

# the rabbitmq-server startup script uses RUNNING_UNDER_SYSTEMD to determine if the erl command
# should be started via exec, which results in beam.smp becoming PID 1 in the container
ENV RUNNING_UNDER_SYSTEMD=true

COPY --from=build /etc/passwd /etc/passwd
COPY --from=build /etc/shadow /etc/shadow
COPY --from=build /etc/group /etc/group

COPY --from=build --chown=lega:lega /home/lega       /home/lega
COPY --from=build /var/empty/sshd  /var/empty/sshd

COPY --from=build /usr/sbin/gosu /usr/sbin/gosu

# ARG ARCH=x86_64
# COPY --from=build /usr/lib/$ARCH-linux-gnu/ /usr/lib/$ARCH-linux-gnu/
COPY --from=build /usr/lib /usr/lib
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /usr/local/lib /usr/local/lib

# RabbitMQ files
COPY --from=rabbitmq /opt/erlang /opt/erlang
COPY --from=rabbitmq /opt/openssl /opt/openssl
COPY --from=rabbitmq /opt/rabbitmq /opt/rabbitmq
COPY --from=rabbitmq --chown=rabbitmq:rabbitmq /etc/rabbitmq /etc/rabbitmq
COPY --from=rabbitmq --chown=rabbitmq:rabbitmq /var/lib/rabbitmq /var/lib/rabbitmq
COPY --from=rabbitmq --chown=rabbitmq:rabbitmq /var/log/rabbitmq /var/log/rabbitmq
COPY --from=rabbitmq --chown=rabbitmq:rabbitmq /tmp/rabbitmq-ssl /tmp/rabbitmq-ssl

# OpenSSH files
COPY --from=build /opt/openssh /opt/openssh

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
    mkdir -m 700 /ega/inbox/upload && \
    chown lega:lega /ega/inbox/upload && \
# make sure the metrics collector is re-enabled
    rm -f /etc/rabbitmq/conf.d/20-management_agent.disable_metrics_collector.conf


COPY conf/sshd_config /etc/ega/sshd_config
COPY conf/pam.ega /etc/pam.d/ega
COPY conf/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=rabbitmq:rabbitmq conf/mq /etc/rabbitmq
COPY conf/banner /etc/ega/banner

VOLUME /ega/inbox/upload
ENV FEGA_INBOX=/ega/inbox/upload

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

ARG COMMIT
ARG BUILD_DATE
LABEL org.label-schema.build-date=$BUILD_DATE
LABEL org.label-schema.vcs-ref=$COMMIT
