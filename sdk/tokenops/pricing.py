"""
sdk/tokenops/pricing.py — Dynamic pricing with 3-tier fallback.

Priority:
  1. TokenOps backend (/pricing) — synced from litellm, manually overridable
  2. litellm.model_cost — 300+ models, updated every release
  3. Hardcoded fallback — top 20 models for offline use

Usage:
    from tokenops.pricing import PricingEngine

    engine = PricingEngine(base_url="http://localhost:8000", api_key="tok_xxx")
    cost = engine.compute(model="gpt-4o", input_tokens=1000, output_tokens=500)
    # $0.0075

    # Or standalone (no backend):
    from tokenops.pricing import compute_cost
    cost = compute_cost("claude-sonnet-4-5", 1000, 500)
"""
import time
from typing import Optional
from loguru import logger


# ═══════════════════════════════════════════════════════════
# Tier 3: Hardcoded fallback — always available
# ═══════════════════════════════════════════════════════════

FALLBACK_PRICING = {
    # Anthropic ($ per 1M tokens)
    "claude-opus-4": {"provider": "anthropic", "input": 15.0, "output": 75.0},
    "claude-sonnet-4-5": {"provider": "anthropic", "input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"provider": "anthropic", "input": 0.8, "output": 4.0},
    # OpenAI
    "gpt-4o": {"provider": "openai", "input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"provider": "openai", "input": 0.15, "output": 0.6},
    "gpt-4-turbo": {"provider": "openai", "input": 10.0, "output": 30.0},
    "o1": {"provider": "openai", "input": 15.0, "output": 60.0},
    "o1-mini": {"provider": "openai", "input": 1.1, "output": 4.4},
    "o3-mini": {"provider": "openai", "input": 1.1, "output": 4.4},
    # Google
    "gemini-2.0-flash": {"provider": "google", "input": 0.1, "output": 0.4},
    "gemini-1.5-pro": {"provider": "google", "input": 1.25, "output": 5.0},
    # Mistral
    "mistral-large-latest": {"provider": "mistral", "input": 2.0, "output": 6.0},
    "mistral-small-latest": {"provider": "mistral", "input": 0.2, "output": 0.6},
    # DeepSeek
    "deepseek-chat": {"provider": "deepseek", "input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"provider": "deepseek", "input": 0.55, "output": 2.19},
    # Groq (hosted open-source)
    "groq/llama-3.1-70b-versatile": {"provider": "groq", "input": 0.59, "output": 0.79},
    "groq/llama-3.1-8b-instant": {"provider": "groq", "input": 0.05, "output": 0.08},
    # Embeddings
    "text-embedding-3-small": {"provider": "openai", "input": 0.02, "output": 0.0},
    "text-embedding-3-large": {"provider": "openai", "input": 0.13, "output": 0.0},
}


# ═══════════════════════════════════════════════════════════
# Tier 2: litellm.model_cost — pip install litellm
# ═══════════════════════════════════════════════════════════

_litellm_cache: Optional[dict] = None
_litellm_cache_ts: float = 0
_CACHE_TTL = 3600  # re-read once per hour


def _get_litellm_pricing() -> dict:
    """Read litellm.model_cost with caching."""
    global _litellm_cache, _litellm_cache_ts

    if _litellm_cache and (time.time() - _litellm_cache_ts) < _CACHE_TTL:
        return _litellm_cache

    try:
        import litellm
        _litellm_cache = litellm.model_cost or {}
        _litellm_cache_ts = time.time()
        return _litellm_cache
    except ImportError:
        return {}
    except Exception:
        return {}


def _litellm_lookup(model: str) -> Optional[dict]:
    """Look up a model in litellm's pricing database."""
    costs = _get_litellm_pricing()
    info = costs.get(model)
    if not info or not isinstance(info, dict):
        # Try common prefixes: openai/gpt-4o, anthropic/claude-...
        for prefix in ["openai/", "anthropic/", "google/", "mistral/", ""]:
            info = costs.get(f"{prefix}{model}")
            if info and isinstance(info, dict):
                break
        else:
            return None

    inp = (info.get("input_cost_per_token") or 0) * 1_000_000
    out = (info.get("output_cost_per_token") or 0) * 1_000_000
    if inp == 0 and out == 0:
        return None

    return {"input": round(inp, 4), "output": round(out, 4)}


# ═══════════════════════════════════════════════════════════
# Tier 1: TokenOps backend — synced & overridable
# ═══════════════════════════════════════════════════════════

_backend_cache: dict = {}
_backend_cache_ts: float = 0
_BACKEND_TTL = 300  # refresh every 5 min


class PricingEngine:
    """
    Dynamic pricing engine with 3-tier fallback.

    Usage:
        engine = PricingEngine(base_url="http://localhost:8000", api_key="tok_xxx")
        cost = engine.compute("gpt-4o", 1000, 500)
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_key = api_key
        self._cache: dict = {}
        self._cache_ts: float = 0

    def _fetch_backend_pricing(self) -> dict:
        """Pull pricing table from TokenOps backend."""
        if not self.base_url:
            return {}
        if self._cache and (time.time() - self._cache_ts) < _BACKEND_TTL:
            return self._cache

        try:
            import httpx
            r = httpx.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                timeout=3.0,
            )
            if r.status_code == 200:
                models = r.json()
                self._cache = {
                    m["model"]: {"input": m.get("input_per_1m", 0), "output": m.get("output_per_1m", 0)}
                    for m in models
                    if isinstance(m, dict)
                }
                self._cache_ts = time.time()
        except Exception:
            pass
        return self._cache

    def lookup(self, model: str) -> dict:
        """
        Look up pricing for a model. Returns {"input": X, "output": Y} per 1M tokens.
        Tries: backend → litellm → hardcoded fallback.
        """
        # Tier 1: Backend
        backend = self._fetch_backend_pricing()
        if model in backend:
            return backend[model]

        # Tier 2: litellm
        ll = _litellm_lookup(model)
        if ll:
            return ll

        # Tier 3: Hardcoded
        fb = FALLBACK_PRICING.get(model)
        if fb:
            return {"input": fb["input"], "output": fb["output"]}

        # Not found — try partial match in fallback
        for key, val in FALLBACK_PRICING.items():
            if key in model or model in key:
                return {"input": val["input"], "output": val["output"]}

        return {"input": 0.0, "output": 0.0}

    def compute(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Compute cost in USD."""
        p = self.lookup(model)
        return round(
            (input_tokens / 1_000_000) * p["input"] +
            (output_tokens / 1_000_000) * p["output"],
            8,
        )


# ═══════════════════════════════════════════════════════════
# Standalone functions (backwards compatible)
# ═══════════════════════════════════════════════════════════

_default_engine: Optional[PricingEngine] = None


def _engine() -> PricingEngine:
    global _default_engine
    if not _default_engine:
        _default_engine = PricingEngine()
    return _default_engine


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute cost using dynamic pricing (litellm → fallback)."""
    return _engine().compute(model, input_tokens, output_tokens)


def compute_unit_cost(model: str, units: int) -> float:
    """For non-token models (video, image, audio)."""
    fb = FALLBACK_PRICING.get(model, {})
    per_unit = fb.get("per_unit", 0)
    return round(units * per_unit, 6)


def get_provider(model: str) -> str:
    """Infer provider from model name."""
    fb = FALLBACK_PRICING.get(model)
    if fb:
        return fb["provider"]

    n = model.lower()
    # Check explicit prefix first (ollama/xxx, groq/xxx, etc.)
    if "/" in n:
        return n.split("/")[0]
    if "claude" in n: return "anthropic"
    if n.startswith("gpt") or n.startswith("o1") or n.startswith("o3"): return "openai"
    if "gemini" in n: return "google"
    if "mistral" in n or "mixtral" in n: return "mistral"
    if "deepseek" in n: return "deepseek"
    if "llama" in n: return "meta"
    if "command" in n: return "cohere"
    return "unknown"


def get_api_type(model: str) -> str:
    n = model.lower()
    if "embed" in n: return "embedding"
    if "tts" in n or "whisper" in n: return "audio"
    if "dall-e" in n or "imagen" in n: return "image"
    return "llm"


# Keep PRICING alias for backwards compatibility
PRICING = FALLBACK_PRICING
