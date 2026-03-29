"""
backend/app/routers/local_llm.py
Auto-discover, health-check, and proxy local LLM instances.
Supports: Ollama, LM Studio, vLLM, llama.cpp server, LocalAI.

Discovery flow:
  1. Scan known default ports
  2. List available models on each instance
  3. Health check with latency
  4. Optional: proxy calls through TokenOps for auto-tracking
"""
import time
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import httpx
from loguru import logger

from ..database import get_db
from ..models import LLMCall, LocalInstance
from ..schemas import LocalInstanceOut, LocalDiscoveryResult, LocalModelInfo

router = APIRouter(prefix="/local", tags=["local-llm"])

# ═══════════════════════════════════════════════════════════
# Known local LLM endpoints
# ═══════════════════════════════════════════════════════════

LOCAL_PROVIDERS = {
    "ollama": {
        "name": "Ollama",
        "default_url": "http://localhost:11434",
        "health_path": "/api/tags",
        "models_path": "/api/tags",
        "chat_path": "/api/chat",
        "generate_path": "/api/generate",
        "model_key": "models",
        "model_name_key": "name",
    },
    "lmstudio": {
        "name": "LM Studio",
        "default_url": "http://localhost:1234",
        "health_path": "/v1/models",
        "models_path": "/v1/models",
        "chat_path": "/v1/chat/completions",
        "model_key": "data",
        "model_name_key": "id",
    },
    "vllm": {
        "name": "vLLM",
        "default_url": "http://localhost:8001",
        "health_path": "/v1/models",
        "models_path": "/v1/models",
        "chat_path": "/v1/chat/completions",
        "model_key": "data",
        "model_name_key": "id",
    },
    "llamacpp": {
        "name": "llama.cpp Server",
        "default_url": "http://localhost:8080",
        "health_path": "/health",
        "models_path": "/v1/models",
        "chat_path": "/v1/chat/completions",
        "model_key": "data",
        "model_name_key": "id",
    },
    "localai": {
        "name": "LocalAI",
        "default_url": "http://localhost:8080",
        "health_path": "/readyz",
        "models_path": "/v1/models",
        "chat_path": "/v1/chat/completions",
        "model_key": "data",
        "model_name_key": "id",
    },
}


# ═══════════════════════════════════════════════════════════
# Discovery & Health Check
# ═══════════════════════════════════════════════════════════

async def _check_instance(provider_key: str, base_url: str) -> dict:
    """Check if a local LLM instance is running and list its models."""
    provider = LOCAL_PROVIDERS.get(provider_key, {})
    result = {
        "provider": provider_key,
        "name": provider.get("name", provider_key),
        "base_url": base_url,
        "status": "offline",
        "latency_ms": 0,
        "models": [],
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Health check
            start = time.monotonic()
            health_url = f"{base_url}{provider.get('health_path', '/health')}"
            r = await client.get(health_url)
            latency_ms = int((time.monotonic() - start) * 1000)

            if r.status_code == 200:
                result["status"] = "online"
                result["latency_ms"] = latency_ms

                # Extract models
                data = r.json()
                model_key = provider.get("model_key", "data")
                name_key = provider.get("model_name_key", "id")

                models_raw = data.get(model_key, [])
                if isinstance(models_raw, list):
                    for m in models_raw:
                        if isinstance(m, dict):
                            model_name = m.get(name_key, "unknown")
                            model_info = {
                                "name": model_name,
                                "size": m.get("size", m.get("vram_required", 0)),
                                "family": m.get("details", {}).get("family", "") if isinstance(m.get("details"), dict) else "",
                                "parameters": m.get("details", {}).get("parameter_size", "") if isinstance(m.get("details"), dict) else "",
                                "quantization": m.get("details", {}).get("quantization_level", "") if isinstance(m.get("details"), dict) else "",
                                "format": m.get("details", {}).get("format", "") if isinstance(m.get("details"), dict) else "",
                            }
                            result["models"].append(model_info)
                        elif isinstance(m, str):
                            result["models"].append({"name": m})
            else:
                result["error"] = f"HTTP {r.status_code}"

    except httpx.ConnectError:
        result["error"] = "Connection refused"
    except httpx.TimeoutException:
        result["error"] = "Timeout"
    except Exception as e:
        result["error"] = str(e)[:200]

    return result


@router.get("/discover", response_model=list[LocalDiscoveryResult])
async def discover_local_llms(
    custom_urls: Optional[str] = Query(None, description="Comma-separated custom URLs to check"),
):
    """
    Auto-discover running local LLM instances.
    Checks default ports for Ollama, LM Studio, vLLM, llama.cpp, LocalAI.
    """
    results = []

    # Check all known providers at their default ports
    for key, provider in LOCAL_PROVIDERS.items():
        result = await _check_instance(key, provider["default_url"])
        results.append(result)

    # Check custom URLs if provided
    if custom_urls:
        for url in custom_urls.split(","):
            url = url.strip().rstrip("/")
            if not url:
                continue
            # Try to detect provider type
            for key in LOCAL_PROVIDERS:
                result = await _check_instance(key, url)
                if result["status"] == "online":
                    results.append(result)
                    break
            else:
                # Try generic OpenAI-compatible check
                result = await _check_instance("lmstudio", url)
                result["provider"] = "custom"
                result["name"] = f"Custom ({url})"
                results.append(result)

    online = [r for r in results if r["status"] == "online"]
    logger.info(f"Local LLM discovery: {len(online)}/{len(results)} instances online")

    return results


@router.get("/instances", response_model=list[LocalInstanceOut])
def list_registered_instances(db: Session = Depends(get_db)):
    """List all registered local LLM instances."""
    from sqlalchemy import select
    return db.execute(select(LocalInstance)).scalars().all()


class RegisterInstanceRequest(BaseModel):
    provider: str = Field(description="ollama, lmstudio, vllm, llamacpp, localai, custom")
    base_url: str = Field(description="Base URL, e.g. http://localhost:11434")
    label: str = Field(default="Default", description="Human-readable label")


@router.post("/instances", response_model=LocalInstanceOut, status_code=201)
async def register_instance(body: RegisterInstanceRequest, db: Session = Depends(get_db)):
    """Register a local LLM instance for continuous monitoring."""
    # Verify it's reachable
    result = await _check_instance(body.provider, body.base_url)

    instance = LocalInstance(
        provider=body.provider,
        base_url=body.base_url.rstrip("/"),
        label=body.label,
        status=result["status"],
        latency_ms=result["latency_ms"],
        models_json=json.dumps(result["models"]),
        last_checked=datetime.utcnow(),
        error_detail=result.get("error"),
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


@router.post("/instances/{instance_id}/check", response_model=LocalDiscoveryResult)
async def check_instance(instance_id: str, db: Session = Depends(get_db)):
    """Run a health check on a registered instance."""
    instance = db.get(LocalInstance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")

    result = await _check_instance(instance.provider, instance.base_url)

    # Update DB
    instance.status = result["status"]
    instance.latency_ms = result["latency_ms"]
    instance.models_json = json.dumps(result["models"])
    instance.last_checked = datetime.utcnow()
    instance.error_detail = result.get("error")
    db.commit()

    return result


# ═══════════════════════════════════════════════════════════
# Proxy — Call local LLMs through TokenOps (auto-tracks usage)
# ═══════════════════════════════════════════════════════════

class LocalChatRequest(BaseModel):
    provider: str = Field(default="ollama", description="ollama, lmstudio, vllm")
    base_url: str = Field(default="http://localhost:11434")
    model: str = Field(description="Model name, e.g. llama3.1, mistral")
    messages: list[dict] = Field(description="Chat messages [{role, content}]")
    project_id: Optional[str] = Field(default=None, description="TokenOps project ID for tracking")
    agent: Optional[str] = Field(default=None, description="Agent name for tracking")
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=32768)
    stream: bool = Field(default=False)


class LocalChatResponse(BaseModel):
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tracked: bool


@router.post("/chat", response_model=LocalChatResponse)
async def proxy_local_chat(
    body: LocalChatRequest,
    db: Session = Depends(get_db),
):
    """
    Proxy a chat completion through a local LLM.
    Automatically tracks token usage in TokenOps (cost = $0).
    Works with any OpenAI-compatible endpoint.
    """
    provider_config = LOCAL_PROVIDERS.get(body.provider, LOCAL_PROVIDERS["lmstudio"])
    base_url = body.base_url.rstrip("/")

    start = time.monotonic()

    try:
        if body.provider == "ollama":
            # Ollama native API
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    f"{base_url}/api/chat",
                    json={
                        "model": body.model,
                        "messages": body.messages,
                        "stream": False,
                        "options": {
                            "temperature": body.temperature,
                            "num_predict": body.max_tokens,
                        },
                    },
                )
                r.raise_for_status()
                data = r.json()

                content = data.get("message", {}).get("content", "")
                input_tokens = data.get("prompt_eval_count", 0)
                output_tokens = data.get("eval_count", 0)
        else:
            # OpenAI-compatible API (LM Studio, vLLM, llama.cpp)
            chat_path = provider_config.get("chat_path", "/v1/chat/completions")
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    f"{base_url}{chat_path}",
                    json={
                        "model": body.model,
                        "messages": body.messages,
                        "temperature": body.temperature,
                        "max_tokens": body.max_tokens,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                data = r.json()

                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)

    except httpx.ConnectError:
        raise HTTPException(503, f"{body.provider} not reachable at {base_url}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"{body.provider} error: {e.response.text[:300]}")
    except Exception as e:
        raise HTTPException(500, f"Local LLM error: {str(e)[:300]}")

    latency_ms = int((time.monotonic() - start) * 1000)

    # Track in TokenOps (cost = $0 for local)
    tracked = False
    if body.project_id:
        try:
            call = LLMCall(
                project_id=body.project_id,
                agent=body.agent,
                model=f"{body.provider}/{body.model}",
                provider=body.provider,
                api_type="llm",
                is_local=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=0.0,
                latency_ms=latency_ms,
                status="ok",
            )
            db.add(call)
            db.commit()
            tracked = True
        except Exception as e:
            logger.warning(f"Failed to track local call: {e}")

    return LocalChatResponse(
        content=content,
        model=body.model,
        provider=body.provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        tracked=tracked,
    )


@router.delete("/instances/{instance_id}", status_code=204)
def delete_instance(instance_id: str, db: Session = Depends(get_db)):
    instance = db.get(LocalInstance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    db.delete(instance)
    db.commit()
