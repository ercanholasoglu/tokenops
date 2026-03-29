"""
backend/app/main.py
TokenOps v1.0 — FastAPI entry point.
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from loguru import logger

from .config import settings
from .database import create_tables, SessionLocal
from .seed import seed_pricing
from .routers import (
    calls, projects, dashboard, model_pricing,
    provider_keys, local_llm, pricing_sync, agent_analytics,
)

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("TokenOps backend starting...")
    create_tables()
    db = SessionLocal()
    try:
        count = seed_pricing(db)
        if count:
            logger.info(f"Seeded {count} model pricing entries")
    finally:
        db.close()
    logger.info("TokenOps API ready — http://localhost:8000/dashboard")
    yield
    logger.info("TokenOps shutting down")


app = FastAPI(
    title="TokenOps API",
    description="LLM Cost Intelligence — track, analyze and optimize AI spending",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────
app.include_router(calls.router)
app.include_router(projects.router)
app.include_router(dashboard.router)
app.include_router(model_pricing.router)
app.include_router(provider_keys.router)
app.include_router(local_llm.router)
app.include_router(pricing_sync.router)
app.include_router(agent_analytics.router)


# ── Dashboard (single HTML) ──────────────────────────
@app.get("/dashboard", response_class=HTMLResponse, tags=["meta"])
def serve_dashboard():
    html_path = STATIC_DIR / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Dashboard not found</h1><p>Expected at backend/static/dashboard.html</p>", status_code=404)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/", tags=["meta"])
def root():
    return {"product": "TokenOps", "version": "1.0.0", "dashboard": "/dashboard", "docs": "/docs"}
