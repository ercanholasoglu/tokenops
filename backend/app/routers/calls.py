"""
backend/app/routers/calls.py
Enhanced: supports all API types, local LLM tracking, extended fields.
"""
import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from ..database import get_db
from ..models import LLMCall, ModelPricing
from ..schemas import CallCreate, CallOut
from ..middleware.auth import get_project_from_key

router = APIRouter(prefix="/calls", tags=["calls"])


def compute_cost(db: Session, model: str, api_type: str,
                 input_tokens: int, output_tokens: int,
                 unit_count: int = 0, duration_sec: float = 0) -> float:
    """Look up model pricing and compute cost based on API type."""
    pricing = db.execute(
        select(ModelPricing).where(ModelPricing.model == model)
    ).scalar_one_or_none()
    if not pricing:
        return 0.0

    if api_type == "llm" or api_type == "embedding":
        inp_cost = (input_tokens / 1_000_000) * (pricing.input_per_1m or 0)
        out_cost = (output_tokens / 1_000_000) * (pricing.output_per_1m or 0)
        return inp_cost + out_cost
    elif pricing.cost_per_unit and pricing.unit_label:
        # Video (per second), Image (per image), Audio (per minute/chars)
        if pricing.unit_label == "second" and duration_sec:
            return duration_sec * pricing.cost_per_unit
        elif pricing.unit_label == "minute" and duration_sec:
            return (duration_sec / 60) * pricing.cost_per_unit
        elif unit_count:
            return unit_count * pricing.cost_per_unit
    return 0.0


@router.post("", response_model=CallOut, status_code=201)
def ingest_call(
    payload: CallCreate,
    project=Depends(get_project_from_key),
    db: Session = Depends(get_db),
):
    cost = payload.cost_usd
    if cost is None:
        cost = compute_cost(
            db, payload.model, payload.api_type,
            payload.input_tokens, payload.output_tokens,
            payload.unit_count or 0, payload.duration_sec or 0,
        )

    # Local LLMs: cost is always 0
    if payload.is_local:
        cost = 0.0

    call = LLMCall(
        project_id=project.id,
        agent=payload.agent,
        model=payload.model,
        provider=payload.provider,
        api_type=payload.api_type,
        is_local=payload.is_local,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cost_usd=cost,
        latency_ms=payload.latency_ms,
        status=payload.status,
        error_msg=payload.error_msg,
        duration_sec=payload.duration_sec,
        resolution=payload.resolution,
        file_size_mb=payload.file_size_mb,
        unit_count=payload.unit_count,
        unit_label=payload.unit_label,
        metadata_=json.dumps(payload.metadata) if payload.metadata else None,
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    return call


@router.get("", response_model=list[CallOut])
def list_calls(
    project_id: Optional[str] = Query(None),
    agent: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    api_type: Optional[str] = Query(None),
    is_local: Optional[bool] = Query(None),
    status: Optional[str] = Query(None),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    q = select(LLMCall).where(LLMCall.created_at >= since)

    if project_id:
        q = q.where(LLMCall.project_id == project_id)
    if agent:
        q = q.where(LLMCall.agent == agent)
    if model:
        q = q.where(LLMCall.model == model)
    if provider:
        q = q.where(LLMCall.provider == provider)
    if api_type:
        q = q.where(LLMCall.api_type == api_type)
    if is_local is not None:
        q = q.where(LLMCall.is_local == is_local)
    if status:
        q = q.where(LLMCall.status == status)

    q = q.order_by(desc(LLMCall.created_at)).limit(limit).offset(offset)
    return db.execute(q).scalars().all()
