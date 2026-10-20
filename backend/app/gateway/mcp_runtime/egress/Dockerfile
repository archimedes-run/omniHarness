# The egress sidecar of a built MCP server (Feature 006, #59).
# Squid (CONNECT allowlist, private-destination ACLs, SNI peek, proxy login,
# token-guarded endpoint) with dnsmasq --stop-dns-rebind as its only resolver.
# Base pinned by digest; packages pinned by version (the approved download).
FROM alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
ARG SQUID_VERSION
ARG DNSMASQ_VERSION
ARG OPENSSL_VERSION
RUN apk add --no-cache "squid=${SQUID_VERSION}" "dnsmasq=${DNSMASQ_VERSION}" "openssl=${OPENSSL_VERSION}" \
 && squid -v | grep -q -- "--with-openssl" \
 && rm -rf /var/cache/apk/*
COPY entrypoint.sh /opt/omni/entrypoint.sh
LABEL omni.egress_version="1"
ENTRYPOINT ["/bin/sh", "/opt/omni/entrypoint.sh"]
