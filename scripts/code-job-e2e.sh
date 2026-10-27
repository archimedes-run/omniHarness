#!/usr/bin/env bash
# End to end for coding jobs (spec 009, Slice 1), against the REAL sandbox
# image (with OpenCode), the real egress proxy and the gateway's real LLM proxy
# and job manager, on throwaway networks. The model is a scripted provider
# behind the proxy (backend/tests/code_jobs/e2e/fake_llm.py): no network for
# the model, no cost. Never touches the live stack.
#
#   scripts/code-job-e2e.sh                     # all checks (see driver.py)
#   E2E_SABOTAGE=nokill scripts/code-job-e2e.sh # Stop does nothing: must FAIL
#
# Needs Docker, the sandbox image (make sandbox-image), the egress image and a
# gateway image with the backend's dependencies (the dev compose's gateway).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX_IMAGE=${SANDBOX_IMAGE:-omni-harness-sandbox:1.11.0-oh5}
EGRESS_IMAGE=${EGRESS_IMAGE:-omni-harness-sandbox-egress:1}
GATEWAY_IMAGE=${GATEWAY_IMAGE:-omni-harness-dev-gateway:latest}
P=oh-cj-e2e-$$
NET_IN=$P-sbx NET_OUT=$P-out VOL=$P-ca
HOST_DIR=$(mktemp -d /tmp/oh-cj-e2e.XXXXXX)
cleanup() {
  for c in $(docker ps -a --format '{{.Names}}' | grep -E "^$P-"); do docker rm -f "$c" >/dev/null 2>&1; done
  docker network rm "$NET_IN" "$NET_OUT" >/dev/null 2>&1
  docker volume rm "$VOL" "$P-venv" >/dev/null 2>&1
  rm -rf "$HOST_DIR"
}
trap cleanup EXIT
rand() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

docker network create --internal "$NET_IN" >/dev/null
docker network create "$NET_OUT" >/dev/null
docker volume create "$VOL" >/dev/null
docker run -d --name "$P-egress" --network "$NET_OUT" --tmpfs /run/egress -v "$VOL:/ca-out" "$EGRESS_IMAGE" >/dev/null
docker network connect "$NET_IN" "$P-egress"
docker run -d --name "$P-fakellm" --network "$NET_OUT" -v "$ROOT/backend/tests/code_jobs/e2e:/e2e:ro" --entrypoint python3 "$GATEWAY_IMAGE" /e2e/fake_llm.py 9999 >/dev/null
# A container on the outside network only: the proxy must be unreachable from it.
docker run -d --name "$P-outsider" --network "$NET_OUT" --entrypoint sleep "$EGRESS_IMAGE" 3600 >/dev/null
for _ in $(seq 1 40); do docker logs "$P-egress" 2>&1 | grep -q "Accepting SSL bumped" && break; sleep 0.5; done

docker create --name "$P-gateway" --network "$NET_OUT" \
  -v "$ROOT/backend:/app/backend" -v "$P-venv:/app/backend/.venv" -v "$HOST_DIR:$HOST_DIR" -v /var/run/docker.sock:/var/run/docker.sock \
  -e OMNI_HARNESS_INTERNAL_AUTH_TOKEN="e2e-secret-$(rand)" -e E2E_PROVIDER_KEY="sk-e2e-provider-$(rand)" -e E2E_CANARY="canary-$(rand)" \
  -e OMNI_HARNESS_SANDBOX_NETWORK="$NET_IN" -e OMNI_HARNESS_SANDBOX_EGRESS_PROXY="http://$P-egress:3128" -e OMNI_HARNESS_SANDBOX_EGRESS_CA_VOLUME="$VOL" \
  -e SANDBOX_IMAGE="$SANDBOX_IMAGE" -e E2E_PREFIX="$P" -e E2E_HOST_DIR="$HOST_DIR" -e E2E_FAKE_LLM="$P-fakellm" -e E2E_OUTSIDER="$P-outsider" \
  -e E2E_SABOTAGE="${E2E_SABOTAGE:-}" -e OMNI_HARNESS_CONFIG_PATH=/app/config.example.yaml -e OPENAI_API_KEY=placeholder \
  -v "$ROOT/config.example.yaml:/app/config.example.yaml:ro" --workdir /app/backend \
  "$GATEWAY_IMAGE" sh -c "PYTHONPATH=. uv run --no-sync python tests/code_jobs/e2e/driver.py" >/dev/null
docker network connect "$NET_IN" "$P-gateway"
docker start -a "$P-gateway"
