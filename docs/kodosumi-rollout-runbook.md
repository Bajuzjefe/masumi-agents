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

Railway-first onboarding (no local runtime required):

1. Ensure the public Kodosumi UI service is healthy:
   - `GET https://aikido-reviewer-kodosumi-ui-production.up.railway.app/health`
2. Register the agent in Koco using OpenAPI from:
   - `https://aikido-reviewer-kodosumi-ui-production.up.railway.app/openapi.json`
3. Confirm Koco can fetch form schema from:
   - `GET https://aikido-reviewer-kodosumi-ui-production.up.railway.app/`
4. Keep API canary disabled until registration and schema sync are verified:
   - `KODOSUMI_ENABLED=false`

## Monitoring checks

- Worker timeout or repeated fallback:
  - `/status.execution_meta.fallback_used=true`
- End-to-end latency:
  - compare canary vs control `duration_ms`
- Payment completion:
  - no increase in `awaiting_payment` stalls
- Kodosumi UI launch health:
  - `POST /` should return a `result` flow id, not Ray startup errors

## Known blocker + mitigation

- Symptom: `The current node timed out during startup` from Ray on Railway UI service.
- Mitigation:
  - keep UI Ray footprint small with:
    - `KODOSUMI_RAY_NUM_CPUS=1`
    - `KODOSUMI_RAY_OBJECT_STORE_MEMORY=78643200`
  - keep launch request bounded:
    - `KODOSUMI_LAUNCH_TIMEOUT_SECONDS=20`

## Rollback

1. Set `KODOSUMI_ENABLED=false` on API service.
2. Keep worker up for debugging or scale down worker.
3. Re-run one paid control E2E.
4. If needed, redeploy previous API image.
