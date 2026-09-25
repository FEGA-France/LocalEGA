FROM debian:13-slim AS build

RUN apt-get update && \
#    apt-get upgrade && \
    apt-get install -y --no-install-recommends \
            vim ca-certificates pkg-config git gcc cmake make automake autoconf libtool patch \
            libsodium-dev libssl-dev libfuse3-dev libcap-dev

RUN echo "alias ll='ls -al'" >> /root/.bashrc

COPY . /var/src

# RUN make && make install

WORKDIR /var/src

ENTRYPOINT ["/bin/sleep"]
CMD ["356d"]
