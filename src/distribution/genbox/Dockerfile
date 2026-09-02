###############################
## Build env
###############################

FROM python:3.14-slim AS build

ENV DEBIAN_FRONTEND noninteractive

RUN pip install --upgrade pip
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

###############################
## Final image
###############################
FROM python:3.14-slim

LABEL maintainer "IFB System Developers"
LABEL org.label-schema.schema-version="2.0"
LABEL org.label-schema.vcs-url="git@github.com:FEGA-France/generate-sqlite-box.git"

COPY --from=build /usr/local/lib/python3.14/ /usr/local/lib/python3.14/

ARG USER_UID=1000
ARG GROUP_GID=10000

RUN groupadd -g ${GROUP_GID} service && \
    useradd -u ${USER_UID} -g ${GROUP_GID} -c 'FEGA Service' -M service

COPY --from=build /usr/local/lib/python3.14/ /usr/local/lib/python3.14/

RUN <<EOFPWD cat > /etc/passwd && <<EOFGRP cat > /etc/group && <<EOFSHADOW cat > /etc/shadow
root:x:0:0:root:/root:/bin/bash
lega:x:${LEGA_UID}:${LEGA_GID}:lega:/nonexistent:/bin/sh
_apt:x:42:65534::/nonexistent:/usr/sbin/nologin
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
    chgrp lega /etc/ega      && \
    chmod 2770 /etc/ega


WORKDIR /lega
ENTRYPOINT ["python", "-m", "code"]
CMD ['/etc/ega/config.ini']

COPY code       /lega/code

RUN chown -R service /ega
USER service

VOLUME /lega/data

ARG COMMIT
ARG BUILD_DATE
LABEL org.label-schema.build-date=$BUILD_DATE
LABEL org.label-schema.vcs-ref=$COMMIT
