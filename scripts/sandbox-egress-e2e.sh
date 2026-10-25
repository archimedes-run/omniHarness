#!/usr/bin/env bash
# End to end for the container sandbox (tests/security/test_sandbox_hardening.py,
# OMNI_SANDBOX_DOCKER_E2E=1). Needs Docker and the network.
#
# Two sandboxes started by the real LocalContainerBackend on a throwaway
# internal network, behind the real egress proxy:
#   * npm install and pip download work (registries, GET);
#   * POST/PUT, other hosts, port 80, other ports, IP literals, the host, and
#     going around the proxy all fail;
#   * sandbox A cannot drive sandbox B's API (no key, or A's own key: 401),
#     while the gateway, which derives B's key, can.
# EGRESS_IMAGE / SANDBOX_IMAGE override the images (the sabotage runs use it).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EGRESS_IMAGE=${EGRESS_IMAGE:-omni-harness-sandbox-egress:1}
SANDBOX_IMAGE=${SANDBOX_IMAGE:-omni-harness-sandbox:1.11.0-oh5}
P=oh-e2e-$$
NET_IN=$P-sbx NET_OUT=$P-out VOL=$P-ca EGRESS=$P-egress
fail=0
cleanup() {
  docker rm -f "$EGRESS" "$P-sandbox-a" "$P-sandbox-b" >/dev/null 2>&1
  docker network rm "$NET_IN" "$NET_OUT" >/dev/null 2>&1
  docker volume rm "$VOL" >/dev/null 2>&1
}
trap cleanup EXIT
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "ok    $1 ($3)"; else echo "FAIL  $1: expected $2, got $3"; fail=1; fi
}

docker network create --internal "$NET_IN" >/dev/null
docker network create "$NET_OUT" >/dev/null
docker volume create "$VOL" >/dev/null
docker run -d --name "$EGRESS" --network "$NET_OUT" --tmpfs /run/egress -v "$VOL:/ca-out" "$EGRESS_IMAGE" >/dev/null
docker network connect --alias omni-e2e-egress "$NET_IN" "$EGRESS"
for _ in $(seq 1 40); do docker logs "$EGRESS" 2>&1 | grep -q "Accepting SSL bumped" && break; sleep 0.5; done

export OMNI_HARNESS_INTERNAL_AUTH_TOKEN="e2e-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export OMNI_HARNESS_SANDBOX_NETWORK="$NET_IN"
export OMNI_HARNESS_SANDBOX_EGRESS_PROXY="http://$EGRESS:3128"
export OMNI_HARNESS_SANDBOX_EGRESS_CA_VOLUME="$VOL"
cd "$ROOT/backend" && uv run --quiet python - "$SANDBOX_IMAGE" "$P" <<'EOF' || fail=1
import sys
from omniharness.community.aio_sandbox.local_backend import LocalContainerBackend
backend = LocalContainerBackend(image=sys.argv[1], base_port=8080, container_prefix=sys.argv[2] + "-sandbox", config_mounts=[], environment={})
backend._runtime = "docker"
for sid in ("a", "b"):
    backend._start_container(f"{sys.argv[2]}-sandbox-{sid}", backend._require_private_network(), [])
EOF
for c in a b; do
  for _ in $(seq 1 60); do docker exec "$P-sandbox-$c" sh -c 'curl -s -o /dev/null --noproxy "*" localhost:8080/' 2>/dev/null && break; sleep 1; done
done

# As the sandbox's own user (the AIO shell API runs as gem, not root).
ex() { docker exec -u gem "$P-sandbox-a" bash -lc "$1" 2>/dev/null; }
code() { ex "curl -s -o /dev/null -w '%{http_code}' --max-time 20 $1" | tail -c 3; }
CA=/etc/omni-egress/ca.crt

ex 'cd /tmp && rm -rf n && mkdir n && cd n && npm init -y >/dev/null && timeout 180 npm install left-pad@1.3.0 --no-fund >/dev/null 2>&1 && test -d node_modules/left-pad' && r=yes || r=no
check "npm install left-pad" yes "$r"
ex 'rm -rf /tmp/p && timeout 180 pip download six==1.16.0 --no-deps -d /tmp/p -q >/dev/null 2>&1 && ls /tmp/p | grep -q six' && r=yes || r=no
check "pip download six" yes "$r"
check "GET registry.npmjs.org"           200 "$(code "--cacert $CA https://registry.npmjs.org/left-pad")"
check "HEAD pypi.org"                    200 "$(code "--cacert $CA -I https://pypi.org/simple/six/")"
check "POST registry.npmjs.org"          403 "$(code "--cacert $CA -X POST https://registry.npmjs.org/-/npm/v1/security/audits")"
check "PUT registry.npmjs.org"           403 "$(code "--cacert $CA -X PUT https://registry.npmjs.org/left-pad")"
check "GET github.com"                   000 "$(code "--cacert $CA https://github.com/")"
check "GET example.com"                  000 "$(code "https://example.com/")"
check "GET http://registry.npmjs.org"    403 "$(code "http://registry.npmjs.org/")"
check "plaintext GET http://pypi.org:443" 403 "$(code "http://pypi.org:443/")"
check "GET registry.npmjs.org:8443"      403 "$(code "--cacert $CA https://registry.npmjs.org:8443/")"
check "GET an IP literal"                403 "$(code "-k https://104.16.0.35/")"
check "GET host.docker.internal"         403 "$(code "-k https://host.docker.internal/")"
check "around the proxy"                 000 "$(code "--noproxy '*' https://registry.npmjs.org/")"
docker logs "$EGRESS" 2>&1 | grep -E 'CONNECT (github\.com|example\.com):443' | grep -vq 'TCP_DENIED' && check "denied CONNECTs never reached upstream" yes no || check "denied CONNECTs never reached upstream" yes yes

check "the CA is readable by the sandbox user" yes "$(ex 'test -r /etc/omni-egress/ca.crt && echo yes || echo no')"
KEY_A=$(docker exec "$P-sandbox-a" printenv SANDBOX_API_KEY)
B="http://$P-sandbox-b:8080/v1/shell/exec"
body='{"command":"echo pwned"}'
check "A -> B exec, no key"   401 "$(code "--noproxy '*' -H 'Content-Type: application/json' -d '$body' $B")"
check "A -> B exec, A's key"  401 "$(code "--noproxy '*' -H 'X-AIO-API-Key: $KEY_A' -H 'Content-Type: application/json' -d '$body' $B")"
# Every GET too, including the image's static-extension exemption matched
# against the query string (review of #103: `&z=.json` read B's files).
docker exec -u gem "$P-sandbox-b" bash -lc 'echo SECRET-FROM-B > /home/gem/secret.txt'
D="http://$P-sandbox-b:8080/v1/file/download?path=/home/gem/secret.txt"
check "A -> B file download, no key" 401 "$(code "--noproxy '*' '$D'")"
for ext in json js css svg png woff2; do
  check "A -> B file download, &z=.$ext" 401 "$(code "--noproxy '*' '$D&z=.$ext'")"
done
check "A -> B /v1/sandbox?z=.json" 401 "$(code "--noproxy '*' 'http://$P-sandbox-b:8080/v1/sandbox?z=.json'")"
# The image's other ways around the key: a Host-routed port proxy on the same
# listener, the absolute-form request line, a case-variant ping into the
# header proxy. None may reach B's API: B's file never reaches A, and a
# command never runs in B (it would create /tmp/pwned there).
BB="http://$P-sandbox-b:8080"
X='{"command":"touch /tmp/pwned; echo PWNED"}'
for h in 8091-x 8081-x 8080-x 8092-x 3000-x; do
  check "A -> B exec with Host: $h"        401 "$(code "--noproxy '*' -H 'Host: $h' -H 'Content-Type: application/json' -d '$X' $BB/v1/shell/exec")"
  check "A -> B download with Host: $h"    401 "$(code "--noproxy '*' -H 'Host: $h' '$D'")"
done
check "A -> B absolute-form request line" 401 "$(code "--noproxy '*' --request-target 'http://8091-x/v1/file/download?path=/home/gem/secret.txt' $BB")"
for ping in /V1/PING /v1/Ping /V1/ping; do
  check "A -> B $ping + x-aio-proxy-port" 401 "$(code "--noproxy '*' -H 'x-aio-proxy-port: 8091' $BB$ping")"
done
check "GET /v1/ping stays open" 200 "$(code "--noproxy '*' $BB/v1/ping")"
leak=no
for h in "" "-H 'Host: 8091-x'" "-H 'Host: 8081-x'"; do
  ex "curl -s --noproxy '*' $h '$D&z=.json'" | grep -q SECRET-FROM-B && leak=yes
done
check "B's file never reaches A" no "$leak"
docker exec "$P-sandbox-b" test -e /tmp/pwned && ran=yes || ran=no
check "no command from A ever ran in B" no "$ran"
cd "$ROOT/backend" && r=$(uv run --quiet python - "$P" <<'EOF'
import subprocess, sys
from omniharness.community.aio_sandbox.sandbox_auth import auth_headers
name = f"{sys.argv[1]}-sandbox-b"
h = auth_headers(name)
out = subprocess.run(["docker", "exec", f"{sys.argv[1]}-sandbox-a", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--noproxy", "*", "-H", f"X-AIO-API-Key: {h['X-AIO-API-Key']}", f"http://{name}:8080/v1/sandbox"], capture_output=True, text=True)
print(out.stdout[-3:])
EOF
)
check "gateway-derived key for B is accepted" 200 "$r"
# A command longer than nginx's 60 s default still returns (it answered 504).
cd "$ROOT/backend" && r=$(uv run --quiet python - "$P" <<'EOF'
import json, subprocess, sys
from omniharness.community.aio_sandbox.sandbox_auth import auth_headers
name = f"{sys.argv[1]}-sandbox-b"
key = auth_headers(name)["X-AIO-API-Key"]
body = json.dumps({"command": "sleep 70; echo LONG-OK"})
out = subprocess.run(["docker", "exec", f"{sys.argv[1]}-sandbox-a", "curl", "-s", "-m", "120", "--noproxy", "*", "-H", f"X-AIO-API-Key: {key}", "-H", "Content-Type: application/json", "-d", body, f"http://{name}:8080/v1/shell/exec"], capture_output=True, text=True)
print("yes" if "LONG-OK" in out.stdout else "no: " + out.stdout[:120])
EOF
)
check "a 70 s command returns" yes "$r"
exit $fail
