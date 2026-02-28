# Kodosumi + Koco Rollout Runbook

Date: 2026-02-28  
Scope: `aikido-reviewer` hybrid deployment on Railway

## Topology

- API service: `aikido-reviewer-api` (public MIP-003 endpoints)
- Worker service: `aikido-reviewer-kodosumi-worker` (private `/internal/execute`)
- OpenAPI form service: `aikido-reviewer-kodosumi-ui` (public `openapi.json`)
- Kodosumi control plane: `aikido-reviewer-kodosumi-panel` (admin frontend + API)

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

Panel service:

- `REGISTER_ENDPOINT` (`https://<kodosumi-ui>/openapi.json`)
- `KODO_ADMIN_EMAIL`
- `KODO_ADMIN_PASSWORD`
- `KODO_SECRET_KEY`
- `KODO_RESET_ADMIN_DB` (`true` once, then `false`)
- `KODO_PATCH_HEALTH_AUTH` (`true`, recommended on Railway)
- `KODO_PATCH_HTTPS_PROXY` (`true`, recommended on Railway)
- `HOST=0.0.0.0`
- `PORT=8080`

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
2. Ensure the panel service is healthy and reachable:
   - `GET https://aikido-reviewer-kodosumi-panel-production.up.railway.app/health`
3. Open panel frontend in browser and login:
   - `https://aikido-reviewer-kodosumi-panel-production.up.railway.app/`
   - sign in as user `admin` with the credential configured via `KODO_ADMIN_PASSWORD`
4. Verify admin screens:
   - `/admin/flow`
   - `/admin/routes`
   - `/admin/timeline/view`
   - `/admin/dashboard`
5. Register the agent in panel/Koco using OpenAPI from:
   - `https://aikido-reviewer-kodosumi-ui-production.up.railway.app/openapi.json`
6. Confirm Koco can fetch form schema from:
   - `GET https://aikido-reviewer-kodosumi-ui-production.up.railway.app/`
7. Keep API canary disabled until registration and schema sync are verified:
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
