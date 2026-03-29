"""
backend/app/routers/pricing_sync.py
Dynamic pricing — syncs model costs from litellm's maintained database.

litellm tracks 300+ models with up-to-date pricing.
This endpoint reads litellm.model_cost and upserts into our ModelPricing table.

No provider has a public pricing API, so litellm is the best maintained source.
It gets updated with every litellm release (weekly).

Endpoints:
  POST /pricing/sync          — Pull latest prices from litellm into DB
  GET  /pricing/sources       — Show where prices come from + last sync time
  GET  /pricing/compare       — Compare our DB prices vs litellm (detect stale)
  PUT  /pricing/{model}       — Manual override for a specific model
"""
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from pydantic import BaseModel, Field
from loguru import logger

from ..database import get_db
from ..models import ModelPricing

router = APIRouter(prefix="/pricing", tags=["pricing"])


def _get_litellm_costs() -> dict:
    """
    Read litellm.model_cost — the most comprehensive LLM pricing database.
    Returns dict of {model_name: {input_cost_per_token, output_cost_per_token, ...}}
    """
    try:
        import litellm
        return litellm.model_cost
    except ImportError:
        logger.warning("litellm not installed — cannot sync dynamic pricing")
        return {}
    except Exception as e:
        logger.error(f"Failed to read litellm.model_cost: {e}")
        return {}


def _classify_provider(model_name: str, litellm_info: dict) -> str:
    """Infer provider from model name and litellm metadata."""
    lp = litellm_info.get("litellm_provider", "")
    if lp:
        mapping = {
            "openai": "OpenAI", "anthropic": "Anthropic", "vertex_ai": "Google",
            "gemini": "Google", "cohere": "Cohere", "mistral": "Mistral",
            "groq": "Groq", "deepseek": "DeepSeek", "fireworks_ai": "Fireworks",
            "together_ai": "Together", "anyscale": "Anyscale", "perplexity": "Perplexity",
            "voyage": "Voyage", "bedrock": "AWS Bedrock", "azure": "Azure",
        }
        for key, name in mapping.items():
            if key in lp.lower():
                return name
        return lp.capitalize()

    # Fallback heuristics
    n = model_name.lower()
    if "claude" in n: return "Anthropic"
    if "gpt" in n or n.startswith("o1") or n.startswith("o3"): return "OpenAI"
    if "gemini" in n: return "Google"
    if "mistral" in n or "mixtral" in n: return "Mistral"
    if "llama" in n: return "Meta"
    if "command" in n: return "Cohere"
    if "deepseek" in n: return "DeepSeek"
    return "Unknown"


def _classify_api_type(model_name: str, litellm_info: dict) -> str:
    """Determine API type from model info."""
    mode = litellm_info.get("mode", "")
    if mode == "embedding": return "embedding"
    if mode == "image_generation": return "image"
    if mode == "audio_transcription" or mode == "audio_speech": return "audio"
    if "embed" in model_name.lower(): return "embedding"
    if "tts" in model_name.lower() or "whisper" in model_name.lower(): return "audio"
    if "dall-e" in model_name.lower() or "image" in model_name.lower(): return "image"
    return "llm"


class SyncResult(BaseModel):
    synced: int
    updated: int
    skipped: int
    errors: int
    source: str
    total_models_in_source: int
    synced_at: datetime


class PricingSource(BaseModel):
    source: str
    version: str
    total_models: int
    last_sync: Optional[datetime]
    db_model_count: int
    stale_count: int


class PriceCompare(BaseModel):
    model: str
    provider: str
    db_input: Optional[float]
    db_output: Optional[float]
    source_input: Optional[float]
    source_output: Optional[float]
    is_stale: bool
    diff_pct: Optional[float]


class ManualPriceUpdate(BaseModel):
    input_per_1m: Optional[float] = None
    output_per_1m: Optional[float] = None
    cost_per_unit: Optional[float] = None
    unit_label: Optional[str] = None
    context_window: Optional[int] = None


@router.post("/sync", response_model=SyncResult)
def sync_pricing_from_litellm(
    filter_providers: Optional[str] = Query(
        None, description="Comma-separated providers to sync: OpenAI,Anthropic,Google"
    ),
    db: Session = Depends(get_db),
):
    """
    Pull latest model pricing from litellm's database and upsert into TokenOps.
    litellm maintains prices for 300+ models, updated with each release.

    Only syncs LLM/embedding models — video/image/audio stay manual.
    """
    costs = _get_litellm_costs()
    if not costs:
        raise HTTPException(503, "Could not read pricing data. Is litellm installed?")

    provider_filter = None
    if filter_providers:
        provider_filter = {p.strip().lower() for p in filter_providers.split(",")}

    synced, updated, skipped, errors = 0, 0, 0, 0

    for model_name, info in costs.items():
        try:
            # Skip non-dict entries
            if not isinstance(info, dict):
                skipped += 1
                continue

            # Get costs (litellm stores per-token, we store per-1M)
            input_cost = info.get("input_cost_per_token", 0) or 0
            output_cost = info.get("output_cost_per_token", 0) or 0

            # Skip models with no pricing info
            if input_cost == 0 and output_cost == 0:
                skipped += 1
                continue

            provider = _classify_provider(model_name, info)
            api_type = _classify_api_type(model_name, info)

            # Apply provider filter
            if provider_filter and provider.lower() not in provider_filter:
                skipped += 1
                continue

            input_per_1m = round(input_cost * 1_000_000, 4)
            output_per_1m = round(output_cost * 1_000_000, 4)
            context = info.get("max_tokens", 0) or info.get("max_input_tokens", 0) or 0

            # Upsert
            existing = db.execute(
                select(ModelPricing).where(ModelPricing.model == model_name)
            ).scalar_one_or_none()

            if existing:
                changed = (
                    existing.input_per_1m != input_per_1m or
                    existing.output_per_1m != output_per_1m
                )
                if changed:
                    existing.input_per_1m = input_per_1m
                    existing.output_per_1m = output_per_1m
                    existing.provider = provider
                    existing.api_type = api_type
                    existing.context_window = context
                    existing.updated_at = datetime.utcnow()
                    updated += 1
                else:
                    skipped += 1
            else:
                db.add(ModelPricing(
                    model=model_name,
                    provider=provider,
                    api_type=api_type,
                    input_per_1m=input_per_1m,
                    output_per_1m=output_per_1m,
                    context_window=context,
                    is_local=False,
                    updated_at=datetime.utcnow(),
                ))
                synced += 1

        except Exception as e:
            logger.warning(f"Failed to sync {model_name}: {e}")
            errors += 1

    db.commit()

    logger.info(f"Pricing sync: {synced} new, {updated} updated, {skipped} skipped, {errors} errors")

    return SyncResult(
        synced=synced, updated=updated, skipped=skipped, errors=errors,
        source="litellm.model_cost",
        total_models_in_source=len(costs),
        synced_at=datetime.utcnow(),
    )


@router.get("/sources", response_model=PricingSource)
def get_pricing_source(db: Session = Depends(get_db)):
    """Show pricing data source info and staleness."""
    costs = _get_litellm_costs()

    # Get litellm version
    try:
        import litellm
        version = litellm.__version__
    except Exception:
        version = "not installed"

    # Count DB models and check staleness
    db_count = db.execute(select(func.count(ModelPricing.id))).scalar() or 0
    last_sync = db.execute(
        select(func.max(ModelPricing.updated_at))
    ).scalar()

    # Count stale entries (not updated in 30+ days)
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)
    stale = db.execute(
        select(func.count(ModelPricing.id)).where(
            ModelPricing.updated_at < cutoff
        )
    ).scalar() or 0

    return PricingSource(
        source="litellm.model_cost",
        version=version,
        total_models=len(costs),
        last_sync=last_sync,
        db_model_count=db_count,
        stale_count=stale,
    )


@router.get("/compare", response_model=list[PriceCompare])
def compare_prices(
    provider: Optional[str] = Query(None),
    only_stale: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Compare DB prices vs litellm source. Shows which models have outdated pricing."""
    costs = _get_litellm_costs()
    q = select(ModelPricing)
    if provider:
        q = q.where(ModelPricing.provider == provider)
    db_models = db.execute(q).scalars().all()

    results = []
    for m in db_models:
        source = costs.get(m.model, {})
        if not isinstance(source, dict):
            continue

        src_input = round((source.get("input_cost_per_token", 0) or 0) * 1e6, 4)
        src_output = round((source.get("output_cost_per_token", 0) or 0) * 1e6, 4)

        db_inp = m.input_per_1m or 0
        is_stale = abs(db_inp - src_input) > 0.001 if src_input > 0 else False
        diff = round(((db_inp - src_input) / src_input * 100), 1) if src_input > 0 else None

        if only_stale and not is_stale:
            continue

        results.append(PriceCompare(
            model=m.model, provider=m.provider,
            db_input=m.input_per_1m, db_output=m.output_per_1m,
            source_input=src_input, source_output=src_output,
            is_stale=is_stale, diff_pct=diff,
        ))

    results.sort(key=lambda x: abs(x.diff_pct or 0), reverse=True)
    return results


@router.put("/{model_name}")
def manual_update_price(
    model_name: str,
    body: ManualPriceUpdate,
    db: Session = Depends(get_db),
):
    """Manually override pricing for a specific model."""
    m = db.execute(
        select(ModelPricing).where(ModelPricing.model == model_name)
    ).scalar_one_or_none()

    if not m:
        raise HTTPException(404, f"Model '{model_name}' not in pricing registry")

    if body.input_per_1m is not None:
        m.input_per_1m = body.input_per_1m
    if body.output_per_1m is not None:
        m.output_per_1m = body.output_per_1m
    if body.cost_per_unit is not None:
        m.cost_per_unit = body.cost_per_unit
    if body.unit_label is not None:
        m.unit_label = body.unit_label
    if body.context_window is not None:
        m.context_window = body.context_window
    m.updated_at = datetime.utcnow()

    db.commit()
    return {"status": "updated", "model": model_name}
