"""
backend/app/routers/dashboard.py
Enhanced aggregated statistics: multi-API, local LLM, agent breakdown, hourly patterns.
"""
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import get_db
from ..models import LLMCall, Project
from ..schemas import (
    DashboardOverview, DailyPoint, ProviderBreakdown, ApiTypeBreakdown,
    ModelStat, ProjectStats, LocalLLMStats, AgentStats, HourlyActivity,
    ProjectDetailAnalytics,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _compute_agent_stats(calls) -> list[AgentStats]:
    agents = defaultdict(lambda: {"calls": 0, "cost": 0.0, "tokens": 0, "models": [], "errors": 0})
    for c in calls:
        a = c.agent or "(no agent)"
        agents[a]["calls"] += 1
        agents[a]["cost"] += c.cost_usd
        agents[a]["tokens"] += c.input_tokens + c.output_tokens
        agents[a]["models"].append(c.model)
        if c.status != "ok":
            agents[a]["errors"] += 1
    return [
        AgentStats(
            agent=k,
            calls=v["calls"],
            cost=round(v["cost"], 4),
            tokens=v["tokens"],
            top_model=max(set(v["models"]), key=v["models"].count) if v["models"] else None,
            error_rate=round(v["errors"] / v["calls"] * 100, 1) if v["calls"] else 0,
        )
        for k, v in sorted(agents.items(), key=lambda x: -x[1]["cost"])
    ]


def _compute_hourly(calls) -> list[HourlyActivity]:
    hours = defaultdict(lambda: {"calls": 0, "cost": 0.0, "tokens": 0})
    for c in calls:
        h = c.created_at.hour
        hours[h]["calls"] += 1
        hours[h]["cost"] += c.cost_usd
        hours[h]["tokens"] += c.input_tokens + c.output_tokens
    return [
        HourlyActivity(hour=h, calls=v["calls"], cost=round(v["cost"], 4), tokens=v["tokens"])
        for h in range(24)
        for v in [hours[h]]
    ]


@router.get("/overview", response_model=DashboardOverview)
def get_overview(
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)

    calls = db.execute(select(LLMCall).where(LLMCall.created_at >= since)).scalars().all()
    prev_calls = db.execute(
        select(LLMCall).where(LLMCall.created_at >= prev_since, LLMCall.created_at < since)
    ).scalars().all()

    # ── Totals ──
    total_cost = sum(c.cost_usd for c in calls)
    total_tokens = sum(c.input_tokens + c.output_tokens for c in calls)
    total_calls_n = len(calls)
    avg_cost = total_cost / total_calls_n if total_calls_n else 0
    prev_cost = sum(c.cost_usd for c in prev_calls)
    cost_trend = ((total_cost - prev_cost) / prev_cost * 100) if prev_cost else 0
    errors = sum(1 for c in calls if c.status != "ok")
    error_rate = round(errors / total_calls_n * 100, 1) if total_calls_n else 0

    # ── Local LLM stats ──
    local_calls = [c for c in calls if c.is_local]
    total_local_calls = len(local_calls)
    total_local_tokens = sum(c.input_tokens + c.output_tokens for c in local_calls)

    local_mdl = defaultdict(lambda: {"provider": "", "calls": 0, "inp": 0, "out": 0, "latency": []})
    for c in local_calls:
        local_mdl[c.model]["provider"] = c.provider
        local_mdl[c.model]["calls"] += 1
        local_mdl[c.model]["inp"] += c.input_tokens
        local_mdl[c.model]["out"] += c.output_tokens
        local_mdl[c.model]["latency"].append(c.latency_ms)

    local_list = [
        LocalLLMStats(
            model=k, provider=v["provider"], calls=v["calls"],
            input_tokens=v["inp"], output_tokens=v["out"],
            avg_latency_ms=round(sum(v["latency"]) / len(v["latency"])) if v["latency"] else 0,
        )
        for k, v in sorted(local_mdl.items(), key=lambda x: -x[1]["calls"])
    ]

    # ── Daily breakdown ──
    daily = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tokens": 0})
    for c in calls:
        day = c.created_at.strftime("%Y-%m-%d")
        daily[day]["cost"] += c.cost_usd
        daily[day]["calls"] += 1
        daily[day]["tokens"] += c.input_tokens + c.output_tokens
    daily_list = [
        DailyPoint(date=k, cost=round(v["cost"], 4), calls=v["calls"], tokens=v["tokens"])
        for k, v in sorted(daily.items())
    ]

    # ── Provider breakdown ──
    prov = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tokens": 0})
    for c in calls:
        prov[c.provider]["cost"] += c.cost_usd
        prov[c.provider]["calls"] += 1
        prov[c.provider]["tokens"] += c.input_tokens + c.output_tokens
    provider_list = [
        ProviderBreakdown(
            provider=k, cost=round(v["cost"], 4), calls=v["calls"], tokens=v["tokens"],
            pct=round(v["cost"] / total_cost * 100, 1) if total_cost else 0,
        )
        for k, v in sorted(prov.items(), key=lambda x: -x[1]["cost"])
    ]

    # ── API Type breakdown ──
    atype = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tokens": 0})
    for c in calls:
        atype[c.api_type]["cost"] += c.cost_usd
        atype[c.api_type]["calls"] += 1
        atype[c.api_type]["tokens"] += c.input_tokens + c.output_tokens
    api_type_list = [
        ApiTypeBreakdown(
            api_type=k, cost=round(v["cost"], 4), calls=v["calls"], tokens=v["tokens"],
            pct=round(v["cost"] / total_cost * 100, 1) if total_cost else 0,
        )
        for k, v in sorted(atype.items(), key=lambda x: -x[1]["cost"])
    ]

    # ── Model stats ──
    mdl = defaultdict(lambda: {"provider": "", "api_type": "llm", "is_local": False, "calls": 0, "inp": 0, "out": 0, "cost": 0.0, "latency": []})
    for c in calls:
        mdl[c.model]["provider"] = c.provider
        mdl[c.model]["api_type"] = c.api_type
        mdl[c.model]["is_local"] = c.is_local
        mdl[c.model]["calls"] += 1
        mdl[c.model]["inp"] += c.input_tokens
        mdl[c.model]["out"] += c.output_tokens
        mdl[c.model]["cost"] += c.cost_usd
        mdl[c.model]["latency"].append(c.latency_ms)
    model_list = [
        ModelStat(
            model=k, provider=v["provider"], api_type=v["api_type"], is_local=v["is_local"],
            calls=v["calls"], input_tokens=v["inp"], output_tokens=v["out"],
            cost=round(v["cost"], 4),
            avg_latency_ms=round(sum(v["latency"]) / len(v["latency"])) if v["latency"] else 0,
        )
        for k, v in sorted(mdl.items(), key=lambda x: -x[1]["cost"])
    ]

    # ── Project stats ──
    projects = db.execute(select(Project).where(Project.active == True)).scalars().all()
    proj_calls = defaultdict(list)
    for c in calls:
        proj_calls[c.project_id].append(c)

    project_list = []
    for p in projects:
        pc = proj_calls.get(p.id, [])
        cost = sum(c.cost_usd for c in pc)
        tokens = sum(c.input_tokens + c.output_tokens for c in pc)
        models_used = [c.model for c in pc]
        top_model = max(set(models_used), key=models_used.count) if models_used else None
        api_types_used = list(set(c.api_type for c in pc))
        lcalls = sum(1 for c in pc if c.is_local)
        project_list.append(ProjectStats(
            project_id=p.id, project_name=p.name, color=p.color,
            total_cost=round(cost, 4), budget=p.budget,
            budget_pct=round(cost / p.budget * 100, 1) if p.budget else 0,
            total_calls=len(pc), total_tokens=tokens,
            top_model=top_model, api_types_used=api_types_used,
            local_calls=lcalls, cloud_calls=len(pc) - lcalls,
        ))

    return DashboardOverview(
        total_cost_month=round(total_cost, 4),
        total_tokens_month=total_tokens,
        total_calls_month=total_calls_n,
        avg_cost_per_call=round(avg_cost, 6),
        cost_trend_pct=round(cost_trend, 1),
        daily_breakdown=daily_list,
        provider_breakdown=provider_list,
        api_type_breakdown=api_type_list,
        model_stats=model_list,
        project_stats=project_list,
        local_llm_stats=local_list,
        agent_stats=_compute_agent_stats(calls),
        hourly_activity=_compute_hourly(calls),
        error_rate=error_rate,
        total_local_calls=total_local_calls,
        total_local_tokens=total_local_tokens,
    )


@router.get("/projects/{project_id}", response_model=ProjectDetailAnalytics)
def get_project_detail(
    project_id: str,
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Deep analytics for a single project."""
    from fastapi import HTTPException
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    now = datetime.utcnow()
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)

    calls = db.execute(
        select(LLMCall).where(LLMCall.project_id == project_id, LLMCall.created_at >= since)
    ).scalars().all()
    prev_calls = db.execute(
        select(LLMCall).where(
            LLMCall.project_id == project_id,
            LLMCall.created_at >= prev_since, LLMCall.created_at < since,
        )
    ).scalars().all()

    total_cost = sum(c.cost_usd for c in calls)
    total_tokens = sum(c.input_tokens + c.output_tokens for c in calls)
    prev_cost = sum(c.cost_usd for c in prev_calls)
    cost_trend = ((total_cost - prev_cost) / prev_cost * 100) if prev_cost else 0
    errors = sum(1 for c in calls if c.status != "ok")
    latencies = [c.latency_ms for c in calls if c.latency_ms > 0]
    local_count = sum(1 for c in calls if c.is_local)

    # Daily
    daily = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tokens": 0})
    for c in calls:
        day = c.created_at.strftime("%Y-%m-%d")
        daily[day]["cost"] += c.cost_usd
        daily[day]["calls"] += 1
        daily[day]["tokens"] += c.input_tokens + c.output_tokens

    # Model stats
    mdl = defaultdict(lambda: {"provider": "", "api_type": "llm", "is_local": False, "calls": 0, "inp": 0, "out": 0, "cost": 0.0, "latency": []})
    for c in calls:
        mdl[c.model]["provider"] = c.provider
        mdl[c.model]["api_type"] = c.api_type
        mdl[c.model]["is_local"] = c.is_local
        mdl[c.model]["calls"] += 1
        mdl[c.model]["inp"] += c.input_tokens
        mdl[c.model]["out"] += c.output_tokens
        mdl[c.model]["cost"] += c.cost_usd
        mdl[c.model]["latency"].append(c.latency_ms)

    # API Type
    atype = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tokens": 0})
    for c in calls:
        atype[c.api_type]["cost"] += c.cost_usd
        atype[c.api_type]["calls"] += 1
        atype[c.api_type]["tokens"] += c.input_tokens + c.output_tokens

    return ProjectDetailAnalytics(
        project_id=project.id,
        project_name=project.name,
        total_cost=round(total_cost, 4),
        budget=project.budget,
        budget_pct=round(total_cost / project.budget * 100, 1) if project.budget else 0,
        total_calls=len(calls),
        total_tokens=total_tokens,
        daily_breakdown=[
            DailyPoint(date=k, cost=round(v["cost"], 4), calls=v["calls"], tokens=v["tokens"])
            for k, v in sorted(daily.items())
        ],
        model_stats=[
            ModelStat(
                model=k, provider=v["provider"], api_type=v["api_type"], is_local=v["is_local"],
                calls=v["calls"], input_tokens=v["inp"], output_tokens=v["out"],
                cost=round(v["cost"], 4),
                avg_latency_ms=round(sum(v["latency"]) / len(v["latency"])) if v["latency"] else 0,
            )
            for k, v in sorted(mdl.items(), key=lambda x: -x[1]["cost"])
        ],
        agent_stats=_compute_agent_stats(calls),
        api_type_breakdown=[
            ApiTypeBreakdown(
                api_type=k, cost=round(v["cost"], 4), calls=v["calls"], tokens=v["tokens"],
                pct=round(v["cost"] / total_cost * 100, 1) if total_cost else 0,
            )
            for k, v in sorted(atype.items(), key=lambda x: -x[1]["cost"])
        ],
        hourly_activity=_compute_hourly(calls),
        error_rate=round(errors / len(calls) * 100, 1) if calls else 0,
        avg_latency_ms=round(sum(latencies) / len(latencies)) if latencies else 0,
        local_calls=local_count,
        cloud_calls=len(calls) - local_count,
        cost_trend_pct=round(cost_trend, 1),
    )
