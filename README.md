# masumi-agents

Masumi-compatible AI agents for the Cardano ecosystem.

## Agents

### Aikido Audit Reviewer

AI-powered triage of [Aikido](https://github.com/Bajuzjefe/aikido) security analysis findings for Aiken smart contracts. Classifies each finding as true/false positive with detailed reasoning, mitigating patterns, and remediation priorities.

**Review tiers:**
- **Quick** (1 USDM) — Heuristic only, instant, zero API cost
- **Standard** (5 USDM) — LLM review for critical/high, batched for medium/low
- **Deep** (10 USDM) — Two-pass with cross-finding correlation

## Setup

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

| Tier | Anthropic Cost | USDM Price | Description |
|------|---------------|------------|-------------|
| Quick | $0.00 | 1 USDM | Heuristic classification, instant |
| Standard | ~$0.20-0.40 | 5 USDM | LLM review for critical/high findings |
| Deep | ~$0.40-0.50 | 10 USDM | Two-pass LLM with correlation |
