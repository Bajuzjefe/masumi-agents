#!/usr/bin/env bash
#
# Railway-first smoke test for a deployed Masumi MIP-003 agent.
#
# This script does NOT run local Docker services. It only calls your deployed
# agent URL and validates the external API flow up to "awaiting_payment".
#
# Required env:
#   AGENT_BASE_URL=https://your-agent.up.railway.app
#
# Optional env:
#   POLL_ATTEMPTS=5
#   POLL_SLEEP_SECONDS=3
#   SAMPLE_REPORT_PATH=agents/aikido-reviewer/tests/fixtures/sample_report.json
#
# Usage:
#   AGENT_BASE_URL=... ./scripts/e2e-railway.sh

set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required."
  exit 1
fi

AGENT_BASE_URL="${AGENT_BASE_URL:-}"
if [[ -z "$AGENT_BASE_URL" ]]; then
  echo "ERROR: AGENT_BASE_URL is required."
  exit 1
fi

POLL_ATTEMPTS="${POLL_ATTEMPTS:-5}"
POLL_SLEEP_SECONDS="${POLL_SLEEP_SECONDS:-3}"
SAMPLE_REPORT_PATH="${SAMPLE_REPORT_PATH:-agents/aikido-reviewer/tests/fixtures/sample_report.json}"

AGENT_BASE_URL="${AGENT_BASE_URL%/}"

echo "=== Railway Agent E2E Smoke ==="
echo "Agent URL: $AGENT_BASE_URL"
echo ""

echo "1) Checking /health"
curl -fsS "$AGENT_BASE_URL/health" | jq .
echo ""

echo "2) Checking /input_schema"
curl -fsS "$AGENT_BASE_URL/input_schema" | jq '.input_data | length'
echo ""

if [[ ! -f "$SAMPLE_REPORT_PATH" ]]; then
  echo "ERROR: sample report not found at $SAMPLE_REPORT_PATH"
  exit 1
fi

REPORT_JSON="$(cat "$SAMPLE_REPORT_PATH")"
SOURCE_FILES_JSON='{"validators/main.ak":"validator main { spend(_datum, _redeemer, _ctx) { True } }"}'

PAYLOAD="$(jq -n \
  --arg report "$REPORT_JSON" \
  --arg source "$SOURCE_FILES_JSON" \
  '{
    input_data: [
      {key: "aikido_report", value: $report},
      {key: "source_files", value: $source}
    ]
  }')"

echo "3) Calling /start_job"
START_RESPONSE="$(curl -fsS -X POST "$AGENT_BASE_URL/start_job" \
  -H "content-type: application/json" \
  -d "$PAYLOAD")"
echo "$START_RESPONSE" | jq '{job_id, payment_id, blockchainIdentifier, sellerVkey, network, agentIdentifier}'
echo ""

JOB_ID="$(echo "$START_RESPONSE" | jq -r '.job_id // empty')"
if [[ -z "$JOB_ID" ]]; then
  echo "ERROR: No job_id returned by /start_job."
  exit 1
fi

echo "4) Polling /status for job_id=$JOB_ID"
for i in $(seq 1 "$POLL_ATTEMPTS"); do
  STATUS="$(curl -fsS "$AGENT_BASE_URL/status?job_id=$JOB_ID")"
  echo "  poll $i: $(echo "$STATUS" | jq -r '.status + " / payment=" + (.payment_status // "unknown")')"
  sleep "$POLL_SLEEP_SECONDS"
done

echo ""
echo "Smoke test completed. Expected pre-payment state is usually 'awaiting_payment'."
