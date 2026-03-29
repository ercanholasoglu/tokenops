"""
backend/app/routers/agent_analytics.py
Agent-level analytics — who spent what, where.

Endpoints:
  GET /analytics/agents                — All agents with token/cost totals
  GET /analytics/agents/{agent}        — Single agent deep dive
  GET /analytics/project-agents        — Project × Agent cross-tabulation
  GET /analytics/agent-timeline        — Agent cost over time (daily)
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, case, and_, desc
from pydantic import BaseModel
from loguru import logger

from ..database import get_db
from ..models import LLMCall, Project

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── Response schemas ──────────────────────────────────────

class AgentSummary(BaseModel):
    agent: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    error_count: int
    error_rate: float
    top_model: Optional[str]
    top_project: Optional[str]
    local_calls: int
    cloud_calls: int
    first_seen: Optional[datetime]
    last_seen: Optional[datetime]


class AgentDetail(BaseModel):
    agent: str
    total_calls: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    models_used: list[dict]      # [{model, calls, tokens, cost}]
    projects_used: list[dict]    # [{project_id, project_name, calls, tokens, cost}]
    daily_usage: list[dict]      # [{date, calls, tokens, cost}]
    api_types: list[dict]        # [{api_type, calls, tokens, cost}]


class ProjectAgentRow(BaseModel):
    project_id: str
    project_name: str
    project_color: str
    agent: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    top_model: Optional[str]
    local_calls: int
    cloud_calls: int


class ProjectAgentMatrix(BaseModel):
    rows: list[ProjectAgentRow]
    project_totals: list[dict]   # [{project_id, name, total_cost, total_tokens}]
    agent_totals: list[dict]     # [{agent, total_cost, total_tokens}]
    grand_total_cost: float
    grand_total_tokens: int


class AgentDailyPoint(BaseModel):
    date: str
    agent: str
    calls: int
    tokens: int
    cost: float


# ── Endpoints ─────────────────────────────────────────────

@router.get("/agents", response_model=list[AgentSummary])
def list_agents(
    days: int = Query(30, ge=1, le=365),
    project_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    All agents with token usage, cost, error rate.
    Sorted by total cost descending.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    q = (
        select(
            LLMCall.agent,
            func.count(LLMCall.id).label("calls"),
            func.sum(LLMCall.input_tokens).label("inp"),
            func.sum(LLMCall.output_tokens).label("out"),
            func.sum(LLMCall.cost_usd).label("cost"),
            func.avg(LLMCall.latency_ms).label("lat"),
            func.sum(case((LLMCall.status == "error", 1), else_=0)).label("errs"),
            func.sum(case((LLMCall.is_local == True, 1), else_=0)).label("local"),
            func.sum(case((LLMCall.is_local == False, 1), else_=0)).label("cloud"),
            func.min(LLMCall.created_at).label("first"),
            func.max(LLMCall.created_at).label("last"),
        )
        .where(LLMCall.created_at >= cutoff)
        .where(LLMCall.agent.isnot(None))
        .group_by(LLMCall.agent)
        .order_by(desc("cost"))
    )

    if project_id:
        q = q.where(LLMCall.project_id == project_id)

    rows = db.execute(q).all()

    results = []
    for r in rows:
        # Find top model for this agent
        top = db.execute(
            select(LLMCall.model, func.count(LLMCall.id).label("c"))
            .where(LLMCall.agent == r.agent)
            .where(LLMCall.created_at >= cutoff)
            .group_by(LLMCall.model)
            .order_by(desc("c"))
            .limit(1)
        ).first()

        # Find top project
        top_proj = db.execute(
            select(Project.name)
            .join(LLMCall, LLMCall.project_id == Project.id)
            .where(LLMCall.agent == r.agent)
            .where(LLMCall.created_at >= cutoff)
            .group_by(Project.name)
            .order_by(desc(func.sum(LLMCall.cost_usd)))
            .limit(1)
        ).scalar()

        total = (r.inp or 0) + (r.out or 0)
        results.append(AgentSummary(
            agent=r.agent,
            total_calls=r.calls,
            total_input_tokens=r.inp or 0,
            total_output_tokens=r.out or 0,
            total_tokens=total,
            total_cost_usd=round(r.cost or 0, 6),
            avg_latency_ms=round(r.lat or 0, 1),
            error_count=r.errs or 0,
            error_rate=round((r.errs or 0) / max(r.calls, 1) * 100, 1),
            top_model=top.model if top else None,
            top_project=top_proj,
            local_calls=r.local or 0,
            cloud_calls=r.cloud or 0,
            first_seen=r.first,
            last_seen=r.last,
        ))

    return results


@router.get("/agents/{agent_name}", response_model=AgentDetail)
def get_agent_detail(
    agent_name: str,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Deep dive into a single agent — models, projects, daily timeline."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    base = and_(LLMCall.agent == agent_name, LLMCall.created_at >= cutoff)

    # Totals
    totals = db.execute(
        select(
            func.count(LLMCall.id),
            func.sum(LLMCall.input_tokens + LLMCall.output_tokens),
            func.sum(LLMCall.cost_usd),
            func.avg(LLMCall.latency_ms),
        ).where(base)
    ).first()

    # Models breakdown
    models = db.execute(
        select(
            LLMCall.model,
            func.count(LLMCall.id).label("calls"),
            func.sum(LLMCall.input_tokens + LLMCall.output_tokens).label("tokens"),
            func.sum(LLMCall.cost_usd).label("cost"),
        ).where(base)
        .group_by(LLMCall.model)
        .order_by(desc("cost"))
    ).all()

    # Projects breakdown
    projects = db.execute(
        select(
            LLMCall.project_id,
            Project.name,
            func.count(LLMCall.id).label("calls"),
            func.sum(LLMCall.input_tokens + LLMCall.output_tokens).label("tokens"),
            func.sum(LLMCall.cost_usd).label("cost"),
        )
        .join(Project, Project.id == LLMCall.project_id)
        .where(base)
        .group_by(LLMCall.project_id, Project.name)
        .order_by(desc("cost"))
    ).all()

    # Daily usage
    daily = db.execute(
        select(
            func.date(LLMCall.created_at).label("day"),
            func.count(LLMCall.id).label("calls"),
            func.sum(LLMCall.input_tokens + LLMCall.output_tokens).label("tokens"),
            func.sum(LLMCall.cost_usd).label("cost"),
        ).where(base)
        .group_by("day")
        .order_by("day")
    ).all()

    # API type breakdown
    api_types = db.execute(
        select(
            LLMCall.api_type,
            func.count(LLMCall.id).label("calls"),
            func.sum(LLMCall.input_tokens + LLMCall.output_tokens).label("tokens"),
            func.sum(LLMCall.cost_usd).label("cost"),
        ).where(base)
        .group_by(LLMCall.api_type)
        .order_by(desc("cost"))
    ).all()

    return AgentDetail(
        agent=agent_name,
        total_calls=totals[0] or 0,
        total_tokens=totals[1] or 0,
        total_cost_usd=round(totals[2] or 0, 6),
        avg_latency_ms=round(totals[3] or 0, 1),
        models_used=[
            {"model": m.model, "calls": m.calls, "tokens": m.tokens or 0, "cost": round(m.cost or 0, 6)}
            for m in models
        ],
        projects_used=[
            {"project_id": p.project_id, "project_name": p.name, "calls": p.calls,
             "tokens": p.tokens or 0, "cost": round(p.cost or 0, 6)}
            for p in projects
        ],
        daily_usage=[
            {"date": str(d.day), "calls": d.calls, "tokens": d.tokens or 0, "cost": round(d.cost or 0, 6)}
            for d in daily
        ],
        api_types=[
            {"api_type": a.api_type, "calls": a.calls, "tokens": a.tokens or 0, "cost": round(a.cost or 0, 6)}
            for a in api_types
        ],
    )


@router.get("/project-agents", response_model=ProjectAgentMatrix)
def project_agent_matrix(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Project × Agent cross-tabulation.
    Shows every (project, agent) combination with token/cost breakdown.
    Includes row totals per project, column totals per agent, and grand total.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Main cross-tab query
    rows_q = (
        select(
            LLMCall.project_id,
            Project.name.label("project_name"),
            Project.color.label("project_color"),
            LLMCall.agent,
            func.count(LLMCall.id).label("calls"),
            func.sum(LLMCall.input_tokens).label("inp"),
            func.sum(LLMCall.output_tokens).label("out"),
            func.sum(LLMCall.cost_usd).label("cost"),
            func.avg(LLMCall.latency_ms).label("lat"),
            func.sum(case((LLMCall.is_local == True, 1), else_=0)).label("local"),
            func.sum(case((LLMCall.is_local == False, 1), else_=0)).label("cloud"),
        )
        .join(Project, Project.id == LLMCall.project_id)
        .where(LLMCall.created_at >= cutoff)
        .where(LLMCall.agent.isnot(None))
        .group_by(LLMCall.project_id, Project.name, Project.color, LLMCall.agent)
        .order_by(desc("cost"))
    )
    rows = db.execute(rows_q).all()

    # Find top model for each (project, agent) pair
    result_rows = []
    for r in rows:
        top = db.execute(
            select(LLMCall.model)
            .where(LLMCall.project_id == r.project_id)
            .where(LLMCall.agent == r.agent)
            .where(LLMCall.created_at >= cutoff)
            .group_by(LLMCall.model)
            .order_by(desc(func.count(LLMCall.id)))
            .limit(1)
        ).scalar()

        total_tok = (r.inp or 0) + (r.out or 0)
        result_rows.append(ProjectAgentRow(
            project_id=r.project_id,
            project_name=r.project_name,
            project_color=r.project_color,
            agent=r.agent,
            total_calls=r.calls,
            total_input_tokens=r.inp or 0,
            total_output_tokens=r.out or 0,
            total_tokens=total_tok,
            total_cost_usd=round(r.cost or 0, 6),
            avg_latency_ms=round(r.lat or 0, 1),
            top_model=top,
            local_calls=r.local or 0,
            cloud_calls=r.cloud or 0,
        ))

    # Project totals
    proj_totals = {}
    for r in result_rows:
        if r.project_id not in proj_totals:
            proj_totals[r.project_id] = {
                "project_id": r.project_id, "name": r.project_name,
                "color": r.project_color,
                "total_cost": 0.0, "total_tokens": 0, "total_calls": 0,
            }
        proj_totals[r.project_id]["total_cost"] += r.total_cost_usd
        proj_totals[r.project_id]["total_tokens"] += r.total_tokens
        proj_totals[r.project_id]["total_calls"] += r.total_calls

    # Agent totals
    agent_totals = {}
    for r in result_rows:
        if r.agent not in agent_totals:
            agent_totals[r.agent] = {
                "agent": r.agent, "total_cost": 0.0, "total_tokens": 0, "total_calls": 0,
            }
        agent_totals[r.agent]["total_cost"] += r.total_cost_usd
        agent_totals[r.agent]["total_tokens"] += r.total_tokens
        agent_totals[r.agent]["total_calls"] += r.total_calls

    grand_cost = sum(r.total_cost_usd for r in result_rows)
    grand_tokens = sum(r.total_tokens for r in result_rows)

    return ProjectAgentMatrix(
        rows=result_rows,
        project_totals=sorted(proj_totals.values(), key=lambda x: x["total_cost"], reverse=True),
        agent_totals=sorted(agent_totals.values(), key=lambda x: x["total_cost"], reverse=True),
        grand_total_cost=round(grand_cost, 6),
        grand_total_tokens=grand_tokens,
    )


@router.get("/agent-timeline", response_model=list[AgentDailyPoint])
def agent_timeline(
    days: int = Query(30, ge=1, le=365),
    agents: Optional[str] = Query(None, description="Comma-separated agent names"),
    project_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Daily cost/token timeline per agent. For stacked area charts."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    q = (
        select(
            func.date(LLMCall.created_at).label("day"),
            LLMCall.agent,
            func.count(LLMCall.id).label("calls"),
            func.sum(LLMCall.input_tokens + LLMCall.output_tokens).label("tokens"),
            func.sum(LLMCall.cost_usd).label("cost"),
        )
        .where(LLMCall.created_at >= cutoff)
        .where(LLMCall.agent.isnot(None))
        .group_by("day", LLMCall.agent)
        .order_by("day")
    )

    if agents:
        agent_list = [a.strip() for a in agents.split(",")]
        q = q.where(LLMCall.agent.in_(agent_list))
    if project_id:
        q = q.where(LLMCall.project_id == project_id)

    rows = db.execute(q).all()

    return [
        AgentDailyPoint(
            date=str(r.day), agent=r.agent,
            calls=r.calls, tokens=r.tokens or 0,
            cost=round(r.cost or 0, 6),
        )
        for r in rows
    ]
