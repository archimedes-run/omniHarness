# The sandboxes' only way out: package registries, read-only (GET/HEAD), 443.
# Squid terminates TLS with a CA it creates at start (name-constrained to the
# registries, trusted only inside sandboxes) so it can see the method.
# Base pinned by digest, packages by version (the same as #59's egress).
FROM alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
ARG SQUID_VERSION
ARG DNSMASQ_VERSION
ARG OPENSSL_VERSION
RUN apk add --no-cache "squid=${SQUID_VERSION}" "dnsmasq=${DNSMASQ_VERSION}" "openssl=${OPENSSL_VERSION}" \
 && squid -v | grep -q -- "--with-openssl" \
 && rm -rf /var/cache/apk/*
COPY squid.conf /etc/squid/sandbox-egress.conf
COPY entrypoint.sh /opt/omni/entrypoint.sh
LABEL omni.sandbox_egress_version="1"
EXPOSE 3128
ENTRYPOINT ["/bin/sh", "/opt/omni/entrypoint.sh"]
