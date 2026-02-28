#!/usr/bin/env bash
#
# Register the Aikido Audit Reviewer agent on the Masumi network.
#
# Prerequisites:
#   1. Masumi node running (docker compose up -d)
#   2. Admin dashboard accessible at http://localhost:3001/admin
#   3. Selling wallet funded with test-ADA from https://dispenser.masumi.network/
#   4. .env.masumi configured with ADMIN_KEY and BLOCKFROST key
#
# Steps performed by this script:
#   1. Check payment service health
#   2. Display wallet info (you must fund it manually)
#   3. Register the agent
#   4. Display the AGENT_IDENTIFIER for your .env
#
# Usage:
#   ./scripts/register-agent.sh

set -euo pipefail

PAYMENT_URL="${PAYMENT_SERVICE_URL:-http://localhost:3001/api/v1}"
ADMIN_KEY="${ADMIN_KEY:-}"
AGENT_API_URL="${AGENT_API_URL:-http://localhost:8011}"

echo "=== Aikido Audit Reviewer — Masumi Registration ==="
echo ""

# 1. Health check
echo "1. Checking payment service health..."
HEALTH=$(curl -s "${PAYMENT_URL%/}/health" 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q "\"status\":\"ok\""; then
    echo "   Payment service is healthy."
else
    # Backward-compatible fallback when PAYMENT_URL is base URL (without /api/v1).
    FALLBACK_HEALTH=$(curl -s "${PAYMENT_URL%/api/v1}/health" 2>/dev/null || echo "FAILED")
    if echo "$FALLBACK_HEALTH" | grep -q "healthy"; then
        echo "   Payment service is healthy."
    else
    echo "   ERROR: Payment service not reachable at ${PAYMENT_URL}"
    echo "   Run: docker compose up -d"
    exit 1
    fi
fi

echo ""
echo "2. Next steps (manual via admin dashboard):"
echo ""
echo "   a) Open http://localhost:3001/admin"
echo "   b) Go to Contracts > PREPROD and note your Selling Wallet address"
echo "   c) Fund it with test-ADA from https://dispenser.masumi.network/"
echo "   d) Register your agent via POST /registry/ with:"
echo ""
echo "      {"
echo "        \"name\": \"Aikido Audit Reviewer\","
echo "        \"description\": \"Deep AI triage of Aikido findings for Aiken smart contracts\","
echo "        \"apiBaseUrl\": \"${AGENT_API_URL}\","
echo "        \"network\": \"Preprod\","
echo "        \"sellingWalletVkey\": \"<from step b>\","
echo "        \"Tags\": [\"security\", \"aikido\", \"aiken\", \"cardano\"],"
echo "        \"Capability\": {\"name\": \"Aikido Security Review\", \"version\": \"1.0.0\"},"
echo "        \"Author\": {\"name\": \"Your Name\"},"
echo "        \"ExampleOutputs\": [{\"name\": \"review_result\", \"url\": \"https://example.com/review-result.json\", \"mimeType\": \"application/json\"}],"
echo "        \"AgentPricing\": {\"pricingType\": \"Fixed\", \"Pricing\": [{\"unit\": \"USDM\", \"amount\": \"4990000\"}]}"
echo "      }"
echo ""
echo "   e) After registration, call GET /registry/ to get your agentIdentifier"
echo "   f) Call GET /api-key/ to get your PAYMENT_API_KEY"
echo ""
echo "3. Then update your .env with:"
echo ""
echo "   AGENT_IDENTIFIER=<from step e>"
echo "   PAYMENT_SERVICE_URL=${PAYMENT_URL}"
echo "   PAYMENT_API_KEY=<from step f>"
echo "   SELLER_VKEY=<from step b>"
echo "   NETWORK=Preprod"
echo ""
echo "4. Start the agent:"
echo "   cd agents/aikido-reviewer"
echo "   python main.py"
echo ""
echo "=== Done ==="
