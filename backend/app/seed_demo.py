"""
backend/app/seed_demo.py
Generates realistic demo data for dashboard screenshots.

Usage:
  cd backend
  python -c "from app.seed_demo import seed_demo; from app.database import SessionLocal; seed_demo(SessionLocal())"

Or from the API:
  POST /seed-demo
"""
import random
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import Project, LLMCall


PROJECTS = [
    {"name": "Customer Chatbot", "slug": "chatbot", "color": "#3b82f6", "budget": 150.0},
    {"name": "Content Pipeline", "slug": "content-pipeline", "color": "#8b5cf6", "budget": 200.0},
    {"name": "Code Assistant", "slug": "code-assist", "color": "#22c55e", "budget": 100.0},
    {"name": "Data Analysis", "slug": "data-analysis", "color": "#f59e0b", "budget": 80.0},
]

AGENTS = {
    "chatbot": [
        {"agent": "router", "models": ["gpt-4o-mini"], "weight": 4},
        {"agent": "responder", "models": ["claude-sonnet-4-5", "gpt-4o"], "weight": 3},
        {"agent": "summarizer", "models": ["gpt-4o-mini"], "weight": 2},
    ],
    "content-pipeline": [
        {"agent": "scout", "models": ["gpt-4o-mini"], "weight": 5},
        {"agent": "writer", "models": ["claude-sonnet-4-5"], "weight": 3},
        {"agent": "editor", "models": ["claude-haiku-4-5", "gpt-4o-mini"], "weight": 4},
        {"agent": "publisher", "models": ["gpt-4o-mini"], "weight": 1},
    ],
    "code-assist": [
        {"agent": "planner", "models": ["claude-sonnet-4-5"], "weight": 2},
        {"agent": "coder", "models": ["claude-sonnet-4-5", "gpt-4o"], "weight": 5},
        {"agent": "reviewer", "models": ["gpt-4o"], "weight": 3},
    ],
    "data-analysis": [
        {"agent": "fetcher", "models": ["gpt-4o-mini"], "weight": 3},
        {"agent": "analyzer", "models": ["claude-sonnet-4-5"], "weight": 4},
        {"agent": "local-llm", "models": ["ollama/llama3.1"], "weight": 6, "is_local": True},
    ],
}

PRICING = {
    "claude-opus-4-5": (15.0, 75.0, "anthropic"),
    "claude-sonnet-4-5": (3.0, 15.0, "anthropic"),
    "claude-haiku-4-5": (0.25, 1.25, "anthropic"),
    "gpt-4o": (2.5, 10.0, "openai"),
    "gpt-4o-mini": (0.15, 0.6, "openai"),
    "gemini-2.0-flash": (0.1, 0.4, "google"),
    "ollama/llama3.1": (0, 0, "ollama"),
    "ollama/mistral": (0, 0, "ollama"),
}


def seed_demo(db: Session, days: int = 30, calls_per_day: int = 40) -> dict:
    """Generate realistic demo data. Returns counts."""

    # Create projects
    project_ids = {}
    for p in PROJECTS:
        existing = db.query(Project).filter(Project.slug == p["slug"]).first()
        if existing:
            project_ids[p["slug"]] = existing.id
            continue
        proj = Project(id=str(uuid.uuid4()), **p)
        db.add(proj)
        db.flush()
        project_ids[p["slug"]] = proj.id

    # Generate calls
    now = datetime.utcnow()
    total_calls = 0

    for day_offset in range(days, 0, -1):
        day = now - timedelta(days=day_offset)

        # Vary calls per day (weekdays busier)
        weekday = day.weekday()
        day_multiplier = 1.2 if weekday < 5 else 0.6
        n_calls = int(calls_per_day * day_multiplier * random.uniform(0.7, 1.3))

        for _ in range(n_calls):
            # Pick a project (weighted: chatbot busiest)
            proj_slug = random.choices(
                list(project_ids.keys()),
                weights=[4, 3, 2, 1],
                k=1,
            )[0]
            proj_id = project_ids[proj_slug]

            # Pick an agent for this project
            agent_pool = AGENTS[proj_slug]
            weights = [a["weight"] for a in agent_pool]
            agent_info = random.choices(agent_pool, weights=weights, k=1)[0]

            model = random.choice(agent_info["models"])
            is_local = agent_info.get("is_local", False)
            provider = PRICING.get(model, (0, 0, "unknown"))[2]

            # Realistic token counts
            input_tokens = random.randint(200, 4000)
            output_tokens = random.randint(100, 2000)

            # Cost
            inp_rate, out_rate, _ = PRICING.get(model, (0, 0, "unknown"))
            cost = (input_tokens / 1e6) * inp_rate + (output_tokens / 1e6) * out_rate

            # Latency (local is slower, small models faster)
            base_latency = 800 if not is_local else 2000
            if "mini" in model or "haiku" in model:
                base_latency = 400
            latency = int(base_latency * random.uniform(0.5, 2.5))

            # Occasional errors (3%)
            status = "error" if random.random() < 0.03 else "ok"
            error_msg = random.choice(["rate limit", "timeout", "context length exceeded"]) if status == "error" else None

            # Random hour (business hours weighted)
            hour = random.choices(range(24), weights=[
                1,1,1,1,1,2, 3,5,8,10,10,9,  # 0-11
                8,9,10,10,8,6, 4,3,2,1,1,1    # 12-23
            ], k=1)[0]
            ts = day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))

            call = LLMCall(
                id=str(uuid.uuid4()),
                project_id=proj_id,
                agent=agent_info["agent"],
                model=model,
                provider=provider,
                api_type="llm",
                is_local=is_local,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6) if status == "ok" else 0,
                latency_ms=latency,
                status=status,
                error_msg=error_msg,
                created_at=ts,
            )
            db.add(call)
            total_calls += 1

    db.commit()

    return {
        "projects": len(PROJECTS),
        "calls": total_calls,
        "days": days,
        "agents": sum(len(v) for v in AGENTS.values()),
    }
