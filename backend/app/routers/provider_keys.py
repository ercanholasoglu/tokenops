"""
backend/app/routers/provider_keys.py
Register external API keys and run health checks to verify they're valid.
"""
import time
import base64
import hashlib
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
import httpx
from loguru import logger

from ..database import get_db
from ..models import ProviderKey, Project
from ..schemas import ProviderKeyCreate, ProviderKeyOut, HealthCheckResult
from ..config import settings

router = APIRouter(prefix="/provider-keys", tags=["provider-keys"])

# Simple encryption using SECRET_KEY (for demo; use Fernet/KMS in production)
def _encrypt(raw: str) -> str:
    key = settings.SECRET_KEY[:32].ljust(32, "0").encode()
    data = raw.encode()
    encrypted = bytes(a ^ b for a, b in zip(data, key * (len(data) // len(key) + 1)))
    return base64.b64encode(encrypted).decode()

def _decrypt(enc: str) -> str:
    key = settings.SECRET_KEY[:32].ljust(32, "0").encode()
    data = base64.b64decode(enc)
    decrypted = bytes(a ^ b for a, b in zip(data, key * (len(data) // len(key) + 1)))
    return decrypted.decode()

def _mask_key(raw: str) -> str:
    if len(raw) <= 8:
        return "***"
    return raw[:4] + "..." + raw[-4:]


# ── Health check functions per provider ──────────────────

HEALTH_CHECKS = {}

def _check_openai(api_key: str) -> dict:
    """Check OpenAI key by listing models."""
    r = httpx.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if r.status_code == 200:
        models = [m["id"] for m in r.json().get("data", [])[:10]]
        return {"valid": True, "models": models}
    return {"valid": False, "error": r.json().get("error", {}).get("message", f"HTTP {r.status_code}")}

def _check_anthropic(api_key: str) -> dict:
    """Check Anthropic key by sending a minimal completion."""
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        },
        timeout=15,
    )
    if r.status_code in (200, 201):
        return {"valid": True, "models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"]}
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    err = data.get("error", {}).get("message", f"HTTP {r.status_code}")
    # Auth error vs rate limit
    if r.status_code == 429:
        return {"valid": True, "models": ["claude-sonnet-4-5", "claude-haiku-4-5"], "error": "Rate limited but key is valid"}
    return {"valid": False, "error": err}

def _check_google(api_key: str) -> dict:
    """Check Google AI key."""
    r = httpx.get(
        f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
        timeout=10,
    )
    if r.status_code == 200:
        models = [m["name"].split("/")[-1] for m in r.json().get("models", [])[:10]]
        return {"valid": True, "models": models}
    return {"valid": False, "error": f"HTTP {r.status_code}"}

def _check_groq(api_key: str) -> dict:
    r = httpx.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if r.status_code == 200:
        models = [m["id"] for m in r.json().get("data", [])[:10]]
        return {"valid": True, "models": models}
    return {"valid": False, "error": f"HTTP {r.status_code}"}

def _check_mistral(api_key: str) -> dict:
    r = httpx.get(
        "https://api.mistral.ai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if r.status_code == 200:
        models = [m["id"] for m in r.json().get("data", [])[:10]]
        return {"valid": True, "models": models}
    return {"valid": False, "error": f"HTTP {r.status_code}"}

def _check_generic(api_key: str) -> dict:
    """For unknown providers, just return unknown status."""
    return {"valid": None, "error": "Health check not implemented for this provider", "models": []}


HEALTH_CHECKS = {
    "openai": _check_openai,
    "anthropic": _check_anthropic,
    "google": _check_google,
    "groq": _check_groq,
    "mistral": _check_mistral,
}


# ── Endpoints ────────────────────────────────────────────

@router.post("/{project_id}", response_model=ProviderKeyOut, status_code=201)
def register_key(
    project_id: str,
    body: ProviderKeyCreate,
    db: Session = Depends(get_db),
):
    """Register an external API key for health monitoring."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    pk = ProviderKey(
        project_id=project_id,
        provider=body.provider.lower(),
        label=body.label,
        key_masked=_mask_key(body.api_key),
        key_encrypted=_encrypt(body.api_key),
        api_type=body.api_type,
    )
    db.add(pk)
    db.commit()
    db.refresh(pk)
    return pk


@router.get("/{project_id}", response_model=list[ProviderKeyOut])
def list_keys(project_id: str, db: Session = Depends(get_db)):
    return db.execute(
        select(ProviderKey).where(ProviderKey.project_id == project_id)
    ).scalars().all()


@router.get("", response_model=list[ProviderKeyOut])
def list_all_keys(db: Session = Depends(get_db)):
    """List all registered provider keys across all projects."""
    return db.execute(select(ProviderKey)).scalars().all()


@router.post("/{project_id}/{key_id}/check", response_model=HealthCheckResult)
def check_key(project_id: str, key_id: str, db: Session = Depends(get_db)):
    """Run a health check on a registered API key."""
    pk = db.get(ProviderKey, key_id)
    if not pk or pk.project_id != project_id:
        raise HTTPException(404, "Key not found")

    raw_key = _decrypt(pk.key_encrypted)
    checker = HEALTH_CHECKS.get(pk.provider, _check_generic)

    start = time.monotonic()
    try:
        result = checker(raw_key)
    except Exception as e:
        result = {"valid": False, "error": str(e), "models": []}
    latency_ms = int((time.monotonic() - start) * 1000)

    # Update DB
    pk.is_valid = result.get("valid")
    pk.last_checked = datetime.utcnow()
    pk.error_detail = result.get("error")
    db.commit()

    return HealthCheckResult(
        provider=pk.provider,
        is_valid=result.get("valid", False),
        latency_ms=latency_ms,
        error_detail=result.get("error"),
        checked_at=datetime.utcnow(),
        models_available=result.get("models", []),
    )


@router.delete("/{project_id}/{key_id}", status_code=204)
def delete_key(project_id: str, key_id: str, db: Session = Depends(get_db)):
    pk = db.get(ProviderKey, key_id)
    if not pk or pk.project_id != project_id:
        raise HTTPException(404, "Key not found")
    db.delete(pk)
    db.commit()
