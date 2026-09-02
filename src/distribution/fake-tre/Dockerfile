##########################
## Build env
##########################
FROM python:3.14-slim AS build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl

RUN pip install --upgrade pip
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt


##########################
## Final image
##########################
FROM python:3.14-slim

LABEL maintainer="IFB System Developers"
LABEL org.label-schema.schema-version="1.0"

COPY --from=build /usr/local/lib/python3.14/ /usr/local/lib/python3.14/
COPY --from=build /lib /lib
COPY --from=build /usr/bin/curl /usr/bin/curl
COPY --from=build /usr/local/bin /usr/local/bin


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

VOLUME /data/vault

# We call it code so make it easier for the logger.json
COPY --chmod=755 script.py /script.py

USER lega
WORKDIR /
ENTRYPOINT ["/bin/sleep"]
CMD ["356d"]

ARG COMMIT
ARG BUILD_DATE
LABEL org.label-schema.build-date=$BUILD_DATE
