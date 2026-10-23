#!/bin/sh
# Create the session-watcher's shared token on first start (security baseline).
# The watcher refuses every request without it; compose mounts the file
# read-only into the watcher and the gateway, whose MCP client sends it.
# Never printed. Idempotent: an existing token is kept.
set -eu
dir="${OMNI_HARNESS_SECRETS_DIR:-$HOME/.omni-harness-secrets}"
file="$dir/watcher.token"
umask 077
mkdir -p "$dir"
chmod 700 "$dir"
if [ ! -s "$file" ]; then
    # 32 random bytes, URL-safe base64, no padding
    head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' >"$file"
    echo >>"$file"
fi
chmod 600 "$file"
