# masumi-agents

Masumi-compatible AI agents for the Cardano ecosystem.

## Agents

### Aikido Audit Reviewer

AI-powered triage of [Aikido](https://github.com/Bajuzjefe/aikido) security analysis findings for Aiken smart contracts. Classifies each finding as true/false positive with detailed reasoning, mitigating patterns, and remediation priorities.

**Single plan:**
- **Deep Analysis** (4.99 USDM) — Two-pass LLM review with cross-finding correlation.

## Setup

### Railway Deployment (agent only)

`railway.toml` is configured to deploy `agents/aikido-reviewer/Dockerfile` and probe `/health`.

Set these Railway variables on the agent service:

- `ANTHROPIC_API_KEY`
- `PAYMENT_SERVICE_URL` (must end with `/api/v1`)
- `PAYMENT_API_KEY`
- `AGENT_IDENTIFIER`
- `SELLER_VKEY`
- `NETWORK=Preprod`

Optional (auto-scan tuning):
- `AIKIDO_TIMEOUT_SECONDS`
- `AIKIDO_GIT_CLONE_TIMEOUT_SECONDS`
- `ALLOWED_REPO_HOSTS`

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

### Funding note (Preprod ADA + USDM)

For Masumi preprod testing, use the official dispenser at [dispenser.masumi.network](https://dispenser.masumi.network/).  
It supports claiming test assets (including ADA and USDM) using the verification code from your Masumi registration email.

If you see repeated `Blockfrost 402 Project Over Limit` errors in payment/registry logs, your E2E payment flow will fail until you replace or upgrade the `BLOCKFROST_API_KEY_PREPROD`.

### Kodosumi (scaling)

```bash
pip install kodosumi ray[serve]
ray start --head
uvicorn agents.aikido_reviewer.kodosumi_app:app --port 8011
# Or deploy via Ray Serve:
serve deploy data/config/config.yaml
```

## How It Works

1. Buyer discovers the agent on [Sokosumi](https://preprod.sokosumi.com/agents) or calls `/start_job` directly
2. Masumi creates a payment request — buyer pays in USDM on Cardano
3. On payment confirmation, the agent runs the Aikido review
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
```

GitHub CI is included at `.github/workflows/ci.yml` and runs `pytest` for every push and pull request.

## Architecture

```
masumi-agents/
├── agents/aikido-reviewer/
│   ├── main.py              # MIP-003 FastAPI (payment-gated)
│   ├── kodosumi_app.py      # Kodosumi runtime entry
│   ├── agent.py             # Pipeline orchestrator
│   ├── analyzer.py          # LLM + heuristic analysis
│   ├── prompts.py           # Domain-aware prompt templates
│   ├── schemas.py           # Pydantic I/O models
│   ├── source_extractor.py  # Code snippet extraction
│   ├── report_builder.py    # Risk scoring + report assembly
│   └── tests/               # 42 unit tests
├── data/config/             # Kodosumi deployment configs
├── docker-compose.yml       # Masumi node (Postgres + Payment + Registry)
├── scripts/                 # Setup and registration scripts
└── .env.masumi.example      # Masumi node config template
```

## Pricing

| Plan | Anthropic Cost | USDM Price | Description |
|------|---------------|------------|-------------|
| Deep Analysis | ~$0.40-0.60 | 4.99 USDM | Two-pass LLM review with correlation |

Masumi `AgentPricing` amount for this price is `4990000` with unit `USDM`.
