# The agent's command sandbox (AioSandboxProvider). The provider speaks the
# AIO sandbox HTTP API (shell sessions, files, Node execution), so this builds
# on the upstream image (Apache-2.0, https://github.com/agent-infra/sandbox),
# pinned by its multi-arch index digest, and removes what we do not use.
#
#   make sandbox-image   ->   omni-harness-sandbox:1.11.0-oh1
FROM ghcr.io/agent-infra/sandbox:1.11.0@sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7

# A cloud vendor's CLI and the outbound proxy service: not used here, and the
# sandbox network has no route out anyway.
RUN rm -f /usr/local/bin/ve /usr/local/bin/linux_amd64_ve /opt/gem/supervisord/supervisord.gost.conf

# Only the API the provider calls runs: no browser, VNC, notebook or editor.
ENV DISABLE_BROWSER=true \
    DISABLE_MCP_BROWSER=true \
    DISABLE_VNC=true \
    DISABLE_JUPYTER=true \
    DISABLE_CODE_SERVER=true

LABEL org.opencontainers.image.source="https://github.com/archimedes-run/omniHarness" \
      org.opencontainers.image.base.name="ghcr.io/agent-infra/sandbox:1.11.0"
