# masumi-agents

Masumi-compatible AI agents for the Cardano ecosystem.

## Agents

### Aikido Audit Reviewer

AI-powered triage of [Aikido](https://github.com/Bajuzjefe/aikido) security analysis findings for Aiken smart contracts. Classifies each finding as true/false positive with detailed reasoning, mitigating patterns, and remediation priorities.

**Single plan:**
- **Deep Analysis** (4.99 USDM) — Two-pass LLM review with cross-finding correlation.

## Setup

### Railway Deployment (hybrid API + Kodosumi worker)

`railway.toml` is configured for API service deployment (`agents/aikido-reviewer/Dockerfile`).
`railway.worker.toml` is provided for the Kodosumi worker service (`agents/aikido-reviewer/Dockerfile.kodosumi-worker`).

Create two Railway services in the same project:

1. `aikido-reviewer-api` (public MIP-003 API)
2. `aikido-reviewer-kodosumi-worker` (internal execution worker)

Set these Railway variables on the API service:

- `ANTHROPIC_API_KEY`
- `PAYMENT_SERVICE_URL` (must end with `/api/v1`)
- `PAYMENT_API_KEY`
- `AGENT_IDENTIFIER`
- `SELLER_VKEY`
- `NETWORK=Preprod`
- `KODOSUMI_ENABLED=false` (default, enable for canary rollout)
- `KODOSUMI_INTERNAL_URL=https://<worker-service>.up.railway.app`
- `KODOSUMI_INTERNAL_TOKEN=<shared-secret>`
- `KODOSUMI_REQUEST_TIMEOUT_SECONDS=90`
- `KODOSUMI_CANARY_HEADER_NAME=x-kodosumi-canary`
- `KODOSUMI_FALLBACK_ON_ERROR=true`

Set these Railway variables on the worker service:

- `ANTHROPIC_API_KEY`
- `KODOSUMI_INTERNAL_TOKEN=<same-shared-secret-as-api>`
- `HOST=0.0.0.0`
- `PORT=8021`

Optional (auto-scan tuning):
- `AIKIDO_TIMEOUT_SECONDS`
- `AIKIDO_GIT_CLONE_TIMEOUT_SECONDS`
- `ALLOWED_REPO_HOSTS`

Suggested Railway config usage:

```bash
# API service
cp railway.toml railway.current.toml

# Worker service (set in Railway service settings or deploy from this file)
cp railway.worker.toml railway.current.toml
```

### 1. Start Masumi node

```bash
cp .env.masumi.example .env.masumi
# Fill in BLOCKFROST_API_KEY_PREPROD and ADMIN_KEY
docker compose up -d
```

### 2. Register agent

```bash
./scripts/register-agent.sh
# Follow prompts — fund wallet, register via admin dashboard, note your identifiers
```

### 3. Configure and start

```bash
cd agents/aikido-reviewer
cp .env.example .env
# Fill in ALL values from registration:
#   ANTHROPIC_API_KEY, PAYMENT_SERVICE_URL, PAYMENT_API_KEY,
#   SELLER_VKEY, AGENT_IDENTIFIER, NETWORK
python main.py
```

The agent will validate all required config on startup and refuse to start if anything is missing.

### Input modes (`/start_job`)

The agent supports two workflows:

- `scan_mode=manual` (default):
  - provide `aikido_report` (Aikido JSON, `aikido.findings.v1`)
  - provide `source_files` (JSON map of path -> source)
- `scan_mode=auto`:
  - provide `source_files` with a full Aiken project (must include `aiken.toml`) OR `repo_url`
  - omit `aikido_report`
  - agent runs Aikido CLI after payment, then performs triage

`review_depth` is deprecated and ignored. The agent always runs deep analysis.

### Execution backend controls

Optional controls for canary routing:

- `input_data` key `execution_backend`:
  - `default` (local execution)
  - `kodosumi` (worker execution, requires `KODOSUMI_ENABLED=true`)
- HTTP header `x-kodosumi-canary: 1` (header name configurable via `KODOSUMI_CANARY_HEADER_NAME`)

`/status` includes:

- `execution_backend`
- `execution_meta.worker_request_id`
- `execution_meta.duration_ms`
- `execution_meta.fallback_used`

### Funding note (Preprod ADA + USDM)

For Masumi preprod testing, use the official dispenser at [dispenser.masumi.network](https://dispenser.masumi.network/).  
It supports claiming test assets (including ADA and USDM) using the verification code from your Masumi registration email.

If you see repeated `Blockfrost 402 Project Over Limit` errors in payment/registry logs, your E2E payment flow will fail until you replace or upgrade the `BLOCKFROST_API_KEY_PREPROD`.

### Kodosumi + Koco (scaling)

Hybrid runtime behavior:

- Default jobs execute in-process on API service.
- Canary jobs can execute on Kodosumi worker by either:
  - `execution_backend=kodosumi` in `input_data`, or
  - request header `x-kodosumi-canary: 1` (when `KODOSUMI_ENABLED=true`).
- Worker failures can automatically fall back to default execution (`KODOSUMI_FALLBACK_ON_ERROR=true`).

Local worker startup:

```bash
cd agents/aikido-reviewer
pip install -r requirements-worker.txt
python worker_main.py
```

Ray Serve + Koco bootstrap:

```bash
# Validate toolchain
./scripts/koco-bootstrap.sh check

# Deploy serve config + app config
./scripts/koco-bootstrap.sh deploy

# Start koco runtime (if needed in your environment)
./scripts/koco-bootstrap.sh start
```

Operational checklist: [docs/kodosumi-rollout-runbook.md](docs/kodosumi-rollout-runbook.md)

## How It Works

1. Buyer discovers the agent on [Sokosumi](https://preprod.sokosumi.com/agents) or calls `/start_job` directly
2. Masumi creates a payment request — buyer pays in USDM on Cardano
3. On payment confirmation, the agent runs the Aikido review:
   - default backend: local in-process pipeline
   - canary backend: Kodosumi worker (`/internal/execute`) with retry + optional fallback
4. Results are delivered via `/status` and settled on-chain

## Testing (development only)

Unit tests validate the pipeline without making LLM calls or requiring payment:

```bash
cd agents/aikido-reviewer
pip install pytest pydantic anthropic
python -m pytest tests/ -v
```

For Railway-first smoke testing (no local docker required):

```bash
# 1) Inspect assigned purchasing/selling wallets on your payment service
PAYMENT_SERVICE_URL=https://<payment-service>/api/v1 \
PAYMENT_ADMIN_TOKEN=<admin-token> \
./scripts/inspect-payment-wallets.sh

# 2) Smoke test deployed agent API flow up to awaiting_payment
AGENT_BASE_URL=https://<agent-service>.up.railway.app \
./scripts/e2e-railway.sh

# Optional: force canary backend request markers in /start_job
AGENT_BASE_URL=https://<agent-service>.up.railway.app \
KODOSUMI_CANARY=1 \
./scripts/e2e-railway.sh
```

GitHub CI is included at `.github/workflows/ci.yml` and runs `pytest` for every push and pull request.

## Architecture

```
masumi-agents/
├── agents/aikido-reviewer/
│   ├── main.py              # MIP-003 FastAPI (payment-gated)
│   ├── execution_backend.py # Backend router + worker client
│   ├── kodosumi_app.py      # Kodosumi form app + internal worker endpoints
│   ├── worker_main.py       # Dedicated worker service entrypoint
│   ├── agent.py             # Pipeline orchestrator
│   ├── analyzer.py          # LLM + heuristic analysis
│   ├── prompts.py           # Domain-aware prompt templates
│   ├── schemas.py           # Pydantic I/O models
│   ├── source_extractor.py  # Code snippet extraction
│   ├── report_builder.py    # Risk scoring + report assembly
│   ├── Dockerfile           # API service image
│   ├── Dockerfile.kodosumi-worker
│   └── tests/               # 42 unit tests
├── data/config/             # Kodosumi deployment configs
├── railway.toml             # API service Railway config
├── railway.worker.toml      # Worker service Railway config
├── docker-compose.yml       # Masumi node (Postgres + Payment + Registry)
├── scripts/                 # Setup and registration scripts
└── .env.masumi.example      # Masumi node config template
```

## Pricing

| Plan | Anthropic Cost | USDM Price | Description |
|------|---------------|------------|-------------|
| Deep Analysis | ~$0.40-0.60 | 4.99 USDM | Two-pass LLM review with correlation |

Masumi `AgentPricing` amount for this price is `4990000` with unit `USDM`.
