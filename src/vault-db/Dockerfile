##########################
## Build env
##########################

FROM postgres:18 AS build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update; \
#    apt-get upgrade -y; \
    apt-get install -y --no-install-recommends \
	    ca-certificates pkg-config git gcc make automake autoconf libtool \
            bzip2 zlib1g-dev libssl-dev libedit-dev libpq-dev postgresql-server-dev-18 \
            cmake 


COPY deps /var/src

######### Libsodium
WORKDIR /var/src/libsodium
RUN autoreconf -i
RUN ./configure --prefix /usr/local \
	--enable-minimal \
        --enable-opt \
        --disable-shared \
        --enable-static \
        --enable-pic
RUN make
RUN make check
RUN make install

######### librabbitmq
WORKDIR /var/src/librabbitmq
RUN mkdir build
WORKDIR /var/src/librabbitmq/build
RUN cmake -DCMAKE_INSTALL_PREFIX=/usr/local ..
RUN cmake --build . --config Release --target install

RUN ldconfig -v

######### Crypt4GH header pgxs
WORKDIR /var/src/pg_crypt4gh
RUN make
RUN make install

######### AMQP pgxs
WORKDIR /var/src/pg_amqp
RUN make
RUN make install

############ For debug
RUN echo "alias ll='ls -al'" >> ~/.bashrc

USER postgres
EXPOSE 5432
ENTRYPOINT ["postgres"]
CMD []

##########################
## Final image
##########################
FROM postgres:18

LABEL maintainer="FEGA-France System Developers"

COPY --from=build /usr/lib/postgresql/18                  /usr/lib/postgresql/18
COPY --from=build /usr/share/postgresql/18                /usr/share/postgresql/18

# Dependencies
COPY --from=build /usr/local/lib/libsodium*        /usr/local/lib/
COPY --from=build /usr/local/lib/librabbitmq*      /usr/local/lib/

RUN ldconfig -v

ENV PGDATA=/ega/data
VOLUME /ega/data

USER postgres
EXPOSE 5432
ENTRYPOINT ["postgres"]
CMD ["-c", "config_file=/etc/ega/pg.conf"]
