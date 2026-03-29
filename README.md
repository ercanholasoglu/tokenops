# TokenOps

LLM cost tracking for teams running multiple models, providers, and agents.

Track every API call — tokens, cost, latency — across OpenAI, Anthropic, Google, local models (Ollama, LM Studio, vLLM), and more.

## Quick Start

```bash
git clone https://github.com/ercanholasoglu/tokenops.git
cd tokenops/backend

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Dashboard: http://localhost:8000/dashboard
# API docs:  http://localhost:8000/docs
```

## SDK

```bash
pip install -e sdk/
```

```python
from tokenops import TokenOps

ops = TokenOps(api_key="tok_live_xxx", project="my-project")

# Manual logging
ops.log(model="gpt-4o", input_tokens=1000, output_tokens=500, agent="writer")

# Auto-tracking (patches OpenAI, Anthropic, litellm)
from tokenops.middleware import patch_all
patch_all(ops)
# Every LLM call is now automatically logged.

# Local LLM (Ollama, LM Studio, vLLM)
from tokenops.local import LocalLLM
llm = LocalLLM(ops=ops, provider="ollama")
response = llm.chat(model="llama3.1", messages=[{"role": "user", "content": "Hi"}])
# Tracked with $0 cost.
```

## Features

**Tracking** — Every call logged with model, tokens, cost, latency, agent name, project.

**Agent analytics** — Per-agent cost breakdown, project × agent cross-tabulation, daily timelines.

**Dynamic pricing** — 300+ model prices synced from litellm. Manual overrides supported.

**Local LLM** — Auto-discover Ollama (11434), LM Studio (1234), vLLM (8001). Proxy calls through TokenOps for automatic tracking at $0.

**Dashboard** — Single HTML page served at `/dashboard`. No Node.js, no build step.

## API Endpoints

```
Core:
  POST /calls                       — Log an API call
  GET  /calls                       — List calls (paginated)
  POST /projects                    — Create project
  GET  /dashboard/overview          — Aggregated stats

Agent Analytics:
  GET  /analytics/agents            — All agents with cost/tokens
  GET  /analytics/agents/{name}     — Single agent deep dive
  GET  /analytics/project-agents    — Project × Agent matrix

Pricing:
  POST /pricing/sync                — Sync prices from litellm
  GET  /pricing/compare             — Detect stale prices
  GET  /models                      — List all model prices

Local LLM:
  GET  /local/discover              — Auto-detect running instances
  POST /local/chat                  — Proxy call with auto-tracking
  POST /local/instances             — Register instance

Provider Keys:
  POST /provider-keys               — Store API key (encrypted)
  POST /provider-keys/{id}/check    — Health check
```

## Project Structure

```
backend/
  app/
    main.py              — FastAPI entry point, serves /dashboard
    models.py            — SQLAlchemy models
    schemas.py           — Pydantic schemas
    routers/
      calls.py           — Call logging
      projects.py        — Project CRUD
      dashboard.py       — Aggregated analytics
      agent_analytics.py — Agent-level breakdown
      pricing_sync.py    — Dynamic pricing from litellm
      local_llm.py       — Local LLM discovery & proxy
      model_pricing.py   — Model price registry
      provider_keys.py   — External API key health
  static/
    dashboard.html       — Single-file dashboard (Chart.js)
  tests/

sdk/
  tokenops/
    client.py            — TokenOps SDK client
    pricing.py           — 3-tier pricing engine
    middleware.py         — Auto-tracking patches
    local.py             — Unified LocalLLM wrapper
  tests/
```

## Tech Stack

FastAPI, SQLAlchemy, SQLite (default) / PostgreSQL, Chart.js, Python SDK.

## License

MIT
