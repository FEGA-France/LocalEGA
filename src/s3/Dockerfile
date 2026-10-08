FROM rustfs/rc:latest AS build

#################################################
##
## Final image
##
#################################################

FROM rustfs/rustfs:latest

LABEL maintainer="IFB System Developers"
LABEL org.label-schema.schema-version="1.0"
LABEL org.label-schema.vcs-url="https://github.com/FEGA-France/LocalEGA"

EXPOSE 9000
EXPOSE 9001

# RustFS rc
COPY --from=build /usr/bin/rc /usr/bin/rc
# COPY --from=build /licenses /licenses

COPY --chmod=755 entrypoint.sh /usr/local/bin/fega-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/fega-entrypoint.sh"]

ARG COMMIT
ARG BUILD_DATE
LABEL org.label-schema.build-date=$BUILD_DATE
LABEL org.label-schema.vcs-ref=$COMMIT
