#!/usr/bin/env bash
#
# Inspect Masumi payment source contracts and assigned wallets (Railway or any remote).
#
# Required env:
#   PAYMENT_SERVICE_URL=https://<payment-service>/api/v1
#   PAYMENT_ADMIN_TOKEN=<admin token or admin key>
#
# Optional env:
#   NETWORK=Preprod
#
# Usage:
#   PAYMENT_SERVICE_URL=... PAYMENT_ADMIN_TOKEN=... ./scripts/inspect-payment-wallets.sh

set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required."
  exit 1
fi

PAYMENT_SERVICE_URL="${PAYMENT_SERVICE_URL:-}"
PAYMENT_ADMIN_TOKEN="${PAYMENT_ADMIN_TOKEN:-${ADMIN_KEY:-}}"
NETWORK="${NETWORK:-Preprod}"

if [[ -z "$PAYMENT_SERVICE_URL" ]]; then
  echo "ERROR: PAYMENT_SERVICE_URL is required."
  exit 1
fi

if [[ -z "$PAYMENT_ADMIN_TOKEN" ]]; then
  echo "ERROR: PAYMENT_ADMIN_TOKEN (or ADMIN_KEY) is required."
  exit 1
fi

PAYMENT_SERVICE_URL="${PAYMENT_SERVICE_URL%/}"
if [[ "$PAYMENT_SERVICE_URL" == */api/v1 ]]; then
  API_BASE="$PAYMENT_SERVICE_URL"
else
  API_BASE="$PAYMENT_SERVICE_URL/api/v1"
fi

echo "=== Masumi Payment Wallet Inspection ==="
echo "API base: $API_BASE"
echo "Network: $NETWORK"
echo ""

echo "1) Health check"
curl -fsS "$API_BASE/health" | jq .
echo ""

echo "2) Loading payment sources"
RAW="$(curl -fsS -H "token: $PAYMENT_ADMIN_TOKEN" "$API_BASE/payment-source-extended/?take=100")"

COUNT="$(echo "$RAW" | jq -r --arg network "$NETWORK" '[.data.ExtendedPaymentSources[] | select(.network == $network)] | length')"
echo "Found $COUNT payment source(s) on $NETWORK."
echo ""

if [[ "$COUNT" == "0" ]]; then
  echo "No payment sources found for network=$NETWORK."
  exit 0
fi

echo "$RAW" | jq -r --arg network "$NETWORK" '
  .data.ExtendedPaymentSources[]
  | select(.network == $network)
  | "PaymentSource: \(.id)\n  PaymentType: \(.paymentType)\n  PolicyId: \(.policyId)\n  SmartContract: \(.smartContractAddress)\n  PurchasingWallets: \(.PurchasingWallets | length)\n  SellingWallets: \(.SellingWallets | length)\n  Purchasing:\n\(.PurchasingWallets[] | "    - id=\(.id) vkey=\(.walletVkey) address=\(.walletAddress)")\n  Selling:\n\(.SellingWallets[] | "    - id=\(.id) vkey=\(.walletVkey) address=\(.walletAddress)")\n"
'
