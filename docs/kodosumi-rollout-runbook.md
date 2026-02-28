# Kodosumi + Koco Rollout Runbook

Date: 2026-02-28  
Scope: `aikido-reviewer` hybrid deployment on Railway

## Topology

- API service: `aikido-reviewer-api` (public MIP-003 endpoints)
- Worker service: `aikido-reviewer-kodosumi-worker` (private `/internal/execute`)

## Required secrets and vars

API service:

- `KODOSUMI_ENABLED`
- `KODOSUMI_INTERNAL_URL`
- `KODOSUMI_INTERNAL_TOKEN`
- `KODOSUMI_REQUEST_TIMEOUT_SECONDS`
- `KODOSUMI_CANARY_HEADER_NAME`
- `KODOSUMI_FALLBACK_ON_ERROR`

Worker service:

- `KODOSUMI_INTERNAL_TOKEN` (must match API)

## Canary rollout

1. Set `KODOSUMI_ENABLED=false` and deploy both services.
2. Verify control path:
   - Submit normal job.
   - Confirm `/status` has `execution_backend=default`.
3. Set `KODOSUMI_ENABLED=true` on API.
4. Submit canary jobs using:
   - header `x-kodosumi-canary: 1`, or
   - `execution_backend=kodosumi`.
5. Validate:
   - `execution_backend=kodosumi`
   - `execution_meta.worker_request_id` populated
   - `payment_status=completed`
6. Run at least 5 canary jobs and 5 control jobs before widening traffic.

## Koco onboarding

1. Validate local tooling:
   - `./scripts/koco-bootstrap.sh check`
2. Deploy:
   - `./scripts/koco-bootstrap.sh deploy`
3. Start runtime if required:
   - `./scripts/koco-bootstrap.sh start`

## Monitoring checks

- Worker timeout or repeated fallback:
  - `/status.execution_meta.fallback_used=true`
- End-to-end latency:
  - compare canary vs control `duration_ms`
- Payment completion:
  - no increase in `awaiting_payment` stalls

## Rollback

1. Set `KODOSUMI_ENABLED=false` on API service.
2. Keep worker up for debugging or scale down worker.
3. Re-run one paid control E2E.
4. If needed, redeploy previous API image.
