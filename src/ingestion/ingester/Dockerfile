##########################
## Build env
##########################
FROM python:3.14-slim AS build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install -y --no-install-recommends \
    	    git make gcc liburing-dev
RUN pip install --upgrade pip

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt


##########################
## Final image
##########################
FROM python:3.14-slim

LABEL maintainer="EGA System Developers"
LABEL org.label-schema.schema-version="2.0"
LABEL org.label-schema.vcs-url="https://github.com/EGA-archive/LocalEGA"

COPY --from=build /usr/local/lib/            /usr/local/lib/
#COPY --from=build /usr/local/lib/python3.14/ /usr/local/lib/python3.14/

# The running user inside the container should not be root
# Since the user will create files, it is convenient to make that
# user the same as the calling user building/using the docker container.
# At the build stage, pass 2 --build-arg arguments and make them match
# the running user, with for example LEGA_UID=$(id -u) and LEGA_GID=$(id -g)
ARG LEGA_UID=1000
ARG LEGA_GID=1000

RUN <<EOFPWD cat > /etc/passwd && <<EOFGRP cat > /etc/group && <<EOFSHADOW cat > /etc/shadow
root:x:0:0:root:/root:/bin/bash
lega:x:${LEGA_UID}:${LEGA_GID}:lega:/nonexistent:/bin/sh
EOFPWD
root:x:0:
shadow:x:1:
lega:x:${LEGA_GID}:lega
EOFGRP
root:*:20507:0:99999:7:::
lega:!:20528:0:99999:7:::
EOFSHADOW

RUN chgrp shadow /etc/shadow && \
    chmod 640    /etc/shadow && \
#
    mkdir -p /etc/ega        && \
    chown lega:lega /etc/ega      && \
    chmod 2770 /etc/ega      && \
# owned by root, not changeable
    mkdir -m 755 /ega        && \
#
    mkdir -p /ega/inbox      && \
    chown lega:lega /ega/inbox    && \
    chmod 2700 /ega/inbox    && \
#
    mkdir -p /ega/staging    && \
    chown lega:lega /ega/staging  && \
    chmod 2700 /ega/staging


# We call it code so make it easier for the logger.json
COPY ingester /ega/code

VOLUME /ega/staging
VOLUME /ega/inbox

USER lega
WORKDIR /ega
ENTRYPOINT ["python", "-m", "code"]
#CMD ["/etc/ega/lega.ini", "ingestion-1"] # injected config file + queue name
