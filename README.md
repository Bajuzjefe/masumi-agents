# masumi-agents

Masumi-compatible AI agents for the Cardano ecosystem.

## Agents

### Aikido Audit Reviewer

AI-powered triage of [Aikido](https://github.com/Bajuzjefe/aikido) security analysis findings for Aiken smart contracts. Classifies each finding as true/false positive with detailed reasoning, mitigating patterns, and remediation priorities.

**Review modes:**
- **Quick** — Heuristic only, instant, zero API cost
- **Standard** — LLM review for critical/high, batched for medium/low
- **Deep** — Two-pass with cross-finding correlation

## Quick Start

### Standalone (no payment, local testing)

```bash
cd agents/aikido-reviewer
pip install pydantic anthropic
python main.py standalone path/to/aikido-report.json quick
```

### API Server (MIP-003, no payment)

```bash
cd agents/aikido-reviewer
pip install -r requirements.txt
cp .env.example .env  # add ANTHROPIC_API_KEY
python main.py
# POST to http://localhost:8011/standalone
```

### Full Masumi Setup (with payment)

```bash
# 1. Start Masumi node
cp .env.masumi.example .env.masumi
# Fill in BLOCKFROST_API_KEY_PREPROD and ADMIN_KEY
docker compose up -d

# 2. Register agent (follow prompts)
./scripts/register-agent.sh

# 3. Start agent
cd agents/aikido-reviewer
cp .env.example .env  # fill in all values from registration
python main.py
```

### Kodosumi (scaling)

```bash
pip install kodosumi ray[serve]
ray start --head
uvicorn agents.aikido_reviewer.kodosumi_app:app --port 8011
# Or deploy via Ray Serve:
serve deploy data/config/config.yaml
```

## Testing

```bash
cd agents/aikido-reviewer
pip install pytest pydantic anthropic
python -m pytest tests/ -v
```

## Architecture

```
masumi-agents/
├── agents/aikido-reviewer/
│   ├── main.py              # MIP-003 FastAPI + standalone CLI
│   ├── kodosumi_app.py      # Kodosumi runtime entry
│   ├── agent.py             # Pipeline orchestrator
│   ├── analyzer.py          # LLM + heuristic analysis
│   ├── prompts.py           # Domain-aware prompt templates
│   ├── schemas.py           # Pydantic I/O models
│   ├── source_extractor.py  # Code snippet extraction
│   ├── report_builder.py    # Risk scoring + report assembly
│   └── tests/               # 41 unit tests
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
