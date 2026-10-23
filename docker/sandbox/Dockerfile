# The agent's command sandbox (AioSandboxProvider). The provider speaks the
# AIO sandbox HTTP API (shell sessions, files, Node execution), so this builds
# on the upstream image (Apache-2.0, https://github.com/agent-infra/sandbox),
# pinned by its multi-arch index digest, and removes what we do not use.
#
#   make sandbox-image   ->   omni-harness-sandbox:1.11.0-oh3
FROM ghcr.io/agent-infra/sandbox:1.11.0@sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7

# A cloud vendor's CLI and the outbound proxy service: not used here, and the
# sandbox network has no route out anyway.
RUN rm -f /usr/local/bin/ve /usr/local/bin/linux_amd64_ve /opt/gem/supervisord/supervisord.gost.conf

# The API key (SANDBOX_API_KEY, one per sandbox) must guard EVERY request to
# :8080; the upstream image left three ways around it (reviews of #103):
#  * GETs whose URI ends in a static-file extension skipped auth, matched
#    against the URI WITH its query string (`...?path=x&z=.json`);
#  * a second server on the same port routed `Host: <port>-x` to that loopback
#    port with no auth (the python API on 8091: shell exec in another sandbox);
#  * the ping exemption matched case-insensitively (`/V1/PING`).
# So: no exemption but an exact, case-sensitive GET /v1/ping; no port-proxy
# server; and the build fails unless the public port has the auth server only.
RUN sed -i '/@proxy_without_auth;/{/GET:\/v1\/ping"/!d}' /opt/gem/nginx-server-with-auth.conf \
 && sed -i 's|"GET:/v1/ping" @proxy_without_auth;|"~^GET:/v1/ping$" @proxy_without_auth;|' /opt/gem/nginx-server-with-auth.conf \
 && : > /opt/gem/nginx-server-port-proxy.conf.template \
 && test "$(grep -c '@proxy_without_auth;' /opt/gem/nginx-server-with-auth.conf)" = 1 \
 && grep -q '"~^GET:/v1/ping$" @proxy_without_auth;' /opt/gem/nginx-server-with-auth.conf \
 && grep -q 'default @proxy_with_auth;' /opt/gem/nginx-server-with-auth.conf \
 && test ! -s /opt/gem/nginx-server-port-proxy.conf.template \
 && test "$(grep -c 'listen ${PUBLIC_LISTEN' /opt/gem/nginx-server-with-auth.conf)" = 2

# Only the API the provider calls runs: no browser, VNC, notebook or editor.
ENV DISABLE_BROWSER=true \
    DISABLE_MCP_BROWSER=true \
    DISABLE_VNC=true \
    DISABLE_JUPYTER=true \
    DISABLE_CODE_SERVER=true

LABEL org.opencontainers.image.source="https://github.com/archimedes-run/omniHarness" \
      org.opencontainers.image.base.name="ghcr.io/agent-infra/sandbox:1.11.0"
