#!/usr/bin/env bash
# End-to-end Composio test: requires COMPOSIO_API_KEY and a running gateway.
# Usage: COMPOSIO_API_KEY=csk_xxx AUTH_TOKEN=<jwt> ./scripts/test_composio_e2e.sh
set -e
BASE=${GATEWAY_URL:-http://localhost:8001}
echo "=== Composio E2E Test ==="
echo "Testing catalog endpoint..."
curl -sf -b "access_token=$AUTH_TOKEN" "$BASE/api/composio/catalog" | jq '.toolkits | length'
echo "Testing connections endpoint..."
curl -sf -b "access_token=$AUTH_TOKEN" "$BASE/api/composio/connections" | jq '.connections | length'
echo "=== DONE ==="
