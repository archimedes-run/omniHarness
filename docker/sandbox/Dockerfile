# The agent's command sandbox (AioSandboxProvider). The provider speaks the
# AIO sandbox HTTP API (shell sessions, files, Node execution), so this builds
# on the upstream image (Apache-2.0, https://github.com/agent-infra/sandbox),
# pinned by its multi-arch index digest, and removes what we do not use.
#
#   make sandbox-image   ->   omni-harness-sandbox:1.11.0-oh5
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

# A command may run for minutes (npm install); the public server's proxy to
# the API used nginx's 60 s default and answered 504 mid-command.
RUN sed -i 's|auth_request /_auth_handler;|auth_request /_auth_handler;\n        proxy_read_timeout 3600s;\n        proxy_send_timeout 3600s;|' /opt/gem/nginx-server-with-auth.conf \
 && grep -q 'proxy_read_timeout 3600s;' /opt/gem/nginx-server-with-auth.conf

# No sudo for the sandbox user (spec 009 FR-017): the upstream start script
# gives it passwordless sudo, which would make every file in the image (the
# coding worker's managed config included) writable by the agent's commands.
# The grant is removed, every setuid/setgid bit is stripped, and the gateway
# starts sandboxes with no-new-privileges. The start script itself runs as
# root and drops to the user with `su`, which needs no setuid bit as root.
RUN sed -i '/^# Add user to sudoers/,/^fi$/d' /opt/gem/gem.sh \
 && ! grep -q 'NOPASSWD\|sudoers' /opt/gem/gem.sh \
 && bash -n /opt/gem/gem.sh \
 && rm -f /etc/sudoers.d/gem \
 && find / -xdev -perm /6000 -type f -exec chmod ug-s {} + \
 && test -z "$(find / -xdev -perm /6000 -type f 2>/dev/null)"

# The coding worker (spec 009, Slice 1): OpenCode (MIT, (c) 2025 opencode,
# https://github.com/anomalyco/opencode), a pinned release verified against
# its published SHA-256. The upstream image ships an older, unpinned build with
# its own default provider and a config renderer; both are replaced. Its
# config is MANAGED (/etc/opencode, the highest precedence, root-owned): our
# one provider is the gateway's LLM proxy (the address and a per-job token come
# from the job's environment; no provider key is ever in the sandbox), every
# other provider is off, sharing and update checks are off, web tools and
# directories outside the workspace are denied, and nothing ever prompts.
ARG TARGETARCH
ARG OPENCODE_VERSION=1.19.3
ARG OPENCODE_SHA256_ARM64=7900818a6a98881edbbadab4b7525940eff3b9750040c200481f9f56cacee405
ARG OPENCODE_SHA256_AMD64=13a8fb2978302071b86f9d7e00da9c8895f9cd846978379c3bdc6a5333536c9b
RUN set -eu; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      arm64) asset=arm64; sum="${OPENCODE_SHA256_ARM64}" ;; \
      amd64) asset=x64; sum="${OPENCODE_SHA256_AMD64}" ;; \
      *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac; \
    rm -f /usr/local/bin/opencode; \
    curl -fsSL -o /tmp/opencode.tar.gz "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${asset}.tar.gz"; \
    echo "${sum}  /tmp/opencode.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin opencode; \
    rm -f /tmp/opencode.tar.gz; \
    chown root:root /usr/local/bin/opencode; chmod 0755 /usr/local/bin/opencode; \
    test "$(HOME=/tmp OPENCODE_DISABLE_AUTOUPDATE=1 OPENCODE_DISABLE_MODELS_FETCH=1 /usr/local/bin/opencode --version 2>/dev/null | tail -n 1)" = "${OPENCODE_VERSION}"; \
    rm -rf /tmp/.local /tmp/.cache /tmp/.config; \
    printf '#!/bin/sh\n# Replaced by OmniHarness: OpenCode config is managed in /etc/opencode.\nexit 0\n' > /opt/gem/render-opencode-config.sh; \
    rm -f /opt/gem/opencode/config.json /opt/gem/nginx/nginx.opencode.conf
COPY --chown=root:root --chmod=0644 opencode/opencode.json /etc/opencode/opencode.json
COPY --chown=root:root --chmod=0644 opencode/AGENTS.md /etc/opencode/AGENTS.md
RUN chmod 0755 /etc/opencode \
 && test "$(stat -c '%U %a' /etc/opencode /etc/opencode/opencode.json /etc/opencode/AGENTS.md | tr '\n' ' ')" = "root 755 root 644 root 644 " \
 && grep -q '"enabled_providers": \["omni"\]' /etc/opencode/opencode.json \
 && ! grep -qi 'api[_-]\?key"[^{]*"[^{]' /etc/opencode/opencode.json
LABEL omni.opencode_version="1.19.3"

# Only the API the provider calls runs: no browser, VNC, notebook or editor.
ENV DISABLE_BROWSER=true \
    DISABLE_MCP_BROWSER=true \
    DISABLE_VNC=true \
    DISABLE_JUPYTER=true \
    DISABLE_CODE_SERVER=true

LABEL org.opencontainers.image.source="https://github.com/archimedes-run/omniHarness" \
      org.opencontainers.image.base.name="ghcr.io/agent-infra/sandbox:1.11.0"
