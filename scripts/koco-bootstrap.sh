#!/usr/bin/env bash
#
# Bootstrap helper for Koco/Kodosumi deployment workflow.
#
# Usage:
#   ./scripts/koco-bootstrap.sh check
#   ./scripts/koco-bootstrap.sh deploy
#   ./scripts/koco-bootstrap.sh start
#
# Optional env:
#   KOCO_CONFIG=data/config/config.yaml
#   KOCO_APP_CONFIG=data/config/aikido-reviewer.yaml

set -euo pipefail

MODE="${1:-check}"
KOCO_CONFIG="${KOCO_CONFIG:-data/config/config.yaml}"
KOCO_APP_CONFIG="${KOCO_APP_CONFIG:-data/config/aikido-reviewer.yaml}"

if ! command -v koco >/dev/null 2>&1; then
  echo "ERROR: koco CLI is not installed or not in PATH."
  echo "Install/setup koco first, then re-run this script."
  exit 1
fi

if ! command -v serve >/dev/null 2>&1; then
  echo "ERROR: ray serve CLI ('serve') is required."
  exit 1
fi

case "$MODE" in
  check)
    echo "koco and serve CLIs are available."
    echo "Config: $KOCO_CONFIG"
    echo "App config: $KOCO_APP_CONFIG"
    ;;
  deploy)
    echo "Deploying Ray Serve base config..."
    serve deploy "$KOCO_CONFIG"
    echo "Applying app config through koco..."
    koco deploy "$KOCO_APP_CONFIG"
    ;;
  start)
    echo "Starting koco runtime..."
    koco start
    ;;
  *)
    echo "ERROR: Unsupported mode '$MODE'. Use: check|deploy|start"
    exit 1
    ;;
esac
