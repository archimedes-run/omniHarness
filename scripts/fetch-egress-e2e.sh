#!/usr/bin/env bash
# End to end for the fetch egress proxy (tests/security/test_fetch_egress.py,
# OMNI_FETCH_EGRESS_E2E=1). Needs Docker, the network, and two local images:
# the sandbox-egress image (built by docker compose) and a python image.
# Nothing it starts is shared with a running stack: a throwaway network and
# containers named oh-fetch-e2e-<pid>-*, removed on exit.
#
#   * http://example.com and https://example.com work through it;
#   * localhost, 127.0.0.1, [::1], 169.254.169.254, a decimal IP literal, a
#     Docker service name (gateway / omni-harness-gateway) and its address,
#     a name that resolves to a private address, a name that resolves to a
#     public AND a private address, other ports, CONNECT to 80, and POST all
#     fail, and none of them reaches the private listener;
#   * a public redirect to a private service fails on the second hop;
#   * the gateway's fetcher, pointed at this proxy, fetches a public page and
#     refuses the service name.
# EGRESS_IMAGE, FETCH_EGRESS_DIR and TARGET_IMAGE override the defaults (the
# sabotage runs point FETCH_EGRESS_DIR at an edited copy of the config).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EGRESS_IMAGE=${EGRESS_IMAGE:-omni-harness-sandbox-egress:1}
TARGET_IMAGE=${TARGET_IMAGE:-python:3.12-slim}
FETCH_EGRESS_DIR=${FETCH_EGRESS_DIR:-$ROOT/docker/fetch-egress}
P=oh-fetch-e2e-$$
NET=$P-net PROXY=$P-proxy TARGET=$P-target
fail=0
cleanup() {
  docker rm -f "$PROXY" "$TARGET" >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
}
trap cleanup EXIT
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "ok    $1 ($3)"; else echo "FAIL  $1: expected $2, got $3"; fail=1; fi
}

docker network create "$NET" >/dev/null || exit 1
# A private service on the same network, named like the gateway; it logs every request.
docker run -d --name "$TARGET" --network "$NET" --network-alias gateway --network-alias omni-harness-gateway \
  "$TARGET_IMAGE" sh -c 'mkdir -p /w && echo TARGET-OK > /w/index.html && cd /w && exec python -u -m http.server 80' >/dev/null || exit 1
TARGET_IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$TARGET")

# The proxy, its resolver pointed at a fake upstream on 127.0.0.2 (started
# below) that answers the test names and forwards the rest to Docker's DNS.
docker run -d --name "$PROXY" --network "$NET" -p 127.0.0.1::3128 --tmpfs /run/fetch \
  -e FETCH_EGRESS_DNS=127.0.0.2 -v "$FETCH_EGRESS_DIR:/opt/fetch:ro" \
  --entrypoint /bin/sh "$EGRESS_IMAGE" /opt/fetch/entrypoint.sh >/dev/null || exit 1
docker exec "$PROXY" dnsmasq --listen-address=127.0.0.2 --bind-interfaces --no-resolv --no-hosts \
  --address=/private.e2e.test/"$TARGET_IP" \
  --address=/mixed.e2e.test/93.184.215.14 --address=/mixed.e2e.test/"$TARGET_IP" \
  --server=127.0.0.11
# A listener on the proxy's own loopback, port 80.
docker exec -d "$PROXY" sh -c 'while true; do printf "HTTP/1.0 200 OK\r\nContent-Length: 9\r\n\r\nLOCAL-OK\n" | nc -l -s 127.0.0.1 -p 80 >/dev/null; done'
for _ in $(seq 1 40); do docker logs "$PROXY" 2>&1 | grep -q "Accepting HTTP" && break; sleep 0.5; done
if ! docker logs "$PROXY" 2>&1 | grep -q "Accepting HTTP"; then
  echo "FAIL  the proxy did not start:"; docker logs "$PROXY" 2>&1 | tail -20; exit 1
fi
PORT=$(docker port "$PROXY" 3128/tcp | head -1 | sed 's/.*://')
X="http://127.0.0.1:$PORT"
echo "proxy $X, private target $TARGET_IP"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 -x "$X" "$@"; }
connect_code() { curl -s -o /dev/null -w '%{http_connect}' --max-time 20 -x "$X" -p "$@"; }
body() { curl -s --max-time 20 -x "$X" "$@"; }
# "denied-403": refused by Squid's ACLs; "denied-503": dnsmasq dropped the
# private answer, so Squid had no address to connect to. Either way the body
# is not the private listener's page.
denied() {
  local c b
  c=$(code "$@"); b=$(body "$@")
  case "$c" in 403|503) ;; *) echo "code=$c"; return ;; esac
  case "$b" in *TARGET-OK*|*LOCAL-OK*) echo "reached"; return ;; esac
  echo "denied-$c"
}

check "GET http://example.com"           200 "$(code http://example.com/)"
check "GET https://example.com"          200 "$(code https://example.com/)"
check "GET http://localhost"             denied-403 "$(denied http://localhost/)"
check "GET http://127.0.0.1"             denied-403 "$(denied http://127.0.0.1/)"
check "CONNECT 127.0.0.1:443"            403 "$(connect_code https://127.0.0.1/)"
check "GET http://[::1]"                 denied-403 "$(denied 'http://[::1]/')"
check "GET http://169.254.169.254"       denied-403 "$(denied http://169.254.169.254/latest/meta-data/)"
check "CONNECT 169.254.169.254:443"      403 "$(connect_code https://169.254.169.254/)"
check "GET http://2130706433 (decimal)"  denied-403 "$(denied http://2130706433/)"
check "GET http://gateway"               denied-403 "$(denied http://gateway/)"
check "GET http://omni-harness-gateway"  denied-403 "$(denied http://omni-harness-gateway/)"
check "GET the service's address"        denied-403 "$(denied "http://$TARGET_IP/")"
check "GET a name -> private address"    denied-503 "$(denied http://private.e2e.test/)"
check "GET a name -> public + private"   denied-503 "$(denied http://mixed.e2e.test/)"
check "CONNECT a name -> private"        503 "$(connect_code https://private.e2e.test/)"
check "GET http://example.com:8080"      403 "$(code http://example.com:8080/)"
check "CONNECT example.com:80"           403 "$(connect_code https://example.com:80/)"
check "CONNECT example.com:8443"         403 "$(connect_code https://example.com:8443/)"
check "POST http://example.com"          403 "$(code -X POST -d x http://example.com/)"

# A public redirect to the private service: the second hop goes back through
# the proxy and is refused there (curl follows, as the gateway does, via the proxy).
first=$(code "https://httpbin.org/redirect-to?url=http://gateway/&status_code=302")
if [ "$first" = "302" ]; then
  final=$(curl -s -L --max-redirs 5 -o /dev/null -w '%{http_code}' --max-time 30 -x "$X" "https://httpbin.org/redirect-to?url=http://gateway/&status_code=302")
  check "redirect public -> gateway"     403 "$final"
  final=$(curl -s -L --max-redirs 5 -o /dev/null -w '%{http_code}' --max-time 30 -x "$X" "https://httpbin.org/redirect-to?url=http://169.254.169.254/&status_code=302")
  check "redirect public -> 169.254.169.254" 403 "$final"
else
  echo "skip  redirect public -> private (httpbin.org answered $first)"
fi

hits=$(docker logs "$TARGET" 2>&1 | grep -c '"GET ')
check "denied requests never reached the private service" 0 "$hits"

# The gateway's own fetcher against this proxy.
cd "$ROOT/backend" && uv run --quiet python - "$X" <<'EOF' || fail=1
import asyncio, sys
from omniharness.community.builtin_fetch.fetcher import FetchSettings, fetch
from omniharness.community.builtin_fetch.extract import to_markdown
from omniharness.community.builtin_fetch.guard import FetchRefused

async def main() -> int:
    s = FetchSettings(proxy=sys.argv[1])
    bad = 0
    page = await fetch("https://example.com/", s)
    ok = page.status == 200 and "Example Domain" in to_markdown(page)
    print(("ok   " if ok else "FAIL ") + " fetcher: https://example.com through the proxy")
    bad += not ok
    for url in ("http://gateway/", "http://localhost/", "http://169.254.169.254/"):
        try:
            await fetch(url, s)
            print(f"FAIL  fetcher: {url} was fetched"); bad += 1
        except FetchRefused as exc:
            print(f"ok    fetcher: {url} refused ({exc})")
    return bad

sys.exit(1 if asyncio.run(main()) else 0)
EOF

exit $fail
