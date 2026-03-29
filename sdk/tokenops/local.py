"""
sdk/tokenops/local.py — Local LLM unified interface with auto-tracking.

Supports: Ollama, LM Studio, vLLM, llama.cpp server, any OpenAI-compatible endpoint.
All calls automatically tracked in TokenOps (cost = $0).

Usage:
    from tokenops import TokenOps
    from tokenops.local import LocalLLM

    ops = TokenOps(api_key="tok_live_xxx")

    # Auto-detect running local instances
    instances = LocalLLM.discover()
    # [{'provider': 'ollama', 'url': 'http://localhost:11434', 'models': ['llama3.1', ...]}]

    # Create a local LLM client
    llm = LocalLLM(ops=ops, provider="ollama")   # auto-detect URL
    # or
    llm = LocalLLM(ops=ops, provider="lmstudio", base_url="http://localhost:1234")

    # List available models
    models = llm.list_models()

    # Chat (auto-tracked in TokenOps)
    response = llm.chat(
        model="llama3.1",
        messages=[{"role": "user", "content": "Hello!"}],
        agent="my-agent",
    )
    print(response.content)
    print(f"Tokens: {response.input_tokens} in, {response.output_tokens} out")
    print(f"Latency: {response.latency_ms}ms")
"""
import time
from dataclasses import dataclass
from typing import Optional
import httpx
from loguru import logger


# Known default endpoints
DEFAULTS = {
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234",
    "vllm": "http://localhost:8001",
    "llamacpp": "http://localhost:8080",
    "localai": "http://localhost:8080",
}


@dataclass
class LocalResponse:
    """Standardized response from any local LLM."""
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw: dict  # Original response data


class LocalLLM:
    """
    Unified local LLM client with auto-tracking.

    Supports Ollama (native API), and any OpenAI-compatible server
    (LM Studio, vLLM, llama.cpp, LocalAI).
    """

    def __init__(
        self,
        ops=None,
        provider: str = "ollama",
        base_url: Optional[str] = None,
        agent: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self.ops = ops
        self.provider = provider
        self.base_url = (base_url or DEFAULTS.get(provider, "http://localhost:11434")).rstrip("/")
        self.default_agent = agent
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ─── Discovery ───────────────────────────────────────

    @staticmethod
    def discover() -> list[dict]:
        """Scan known ports and return list of running local LLM instances."""
        results = []
        for provider, url in DEFAULTS.items():
            try:
                check_url = f"{url}/api/tags" if provider == "ollama" else f"{url}/v1/models"
                r = httpx.get(check_url, timeout=3.0)
                if r.status_code == 200:
                    data = r.json()
                    if provider == "ollama":
                        models = [m["name"] for m in data.get("models", [])]
                    else:
                        models = [m["id"] for m in data.get("data", [])]
                    results.append({
                        "provider": provider,
                        "url": url,
                        "status": "online",
                        "models": models,
                    })
            except Exception:
                pass
        return results

    # ─── Model listing ───────────────────────────────────

    def list_models(self) -> list[dict]:
        """List available models on this instance."""
        try:
            if self.provider == "ollama":
                r = self._client.get("/api/tags")
                r.raise_for_status()
                return [
                    {
                        "name": m["name"],
                        "size_gb": round(m.get("size", 0) / 1e9, 1),
                        "family": m.get("details", {}).get("family", ""),
                        "parameters": m.get("details", {}).get("parameter_size", ""),
                        "quantization": m.get("details", {}).get("quantization_level", ""),
                    }
                    for m in r.json().get("models", [])
                ]
            else:
                r = self._client.get("/v1/models")
                r.raise_for_status()
                return [
                    {"name": m["id"], "owned_by": m.get("owned_by", "")}
                    for m in r.json().get("data", [])
                ]
        except Exception as e:
            logger.warning(f"LocalLLM: failed to list models: {e}")
            return []

    # ─── Chat completion ─────────────────────────────────

    def chat(
        self,
        model: str,
        messages: list[dict],
        agent: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        metadata: Optional[dict] = None,
    ) -> LocalResponse:
        """
        Send a chat completion to the local LLM.
        Automatically tracks in TokenOps if ops is set.
        """
        start = time.monotonic()
        status = "ok"
        error_msg = None

        try:
            if self.provider == "ollama":
                r = self._client.post(
                    "/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": temperature, "num_predict": max_tokens},
                    },
                )
                r.raise_for_status()
                data = r.json()
                content = data.get("message", {}).get("content", "")
                input_tokens = data.get("prompt_eval_count", 0)
                output_tokens = data.get("eval_count", 0)
            else:
                r = self._client.post(
                    "/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
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
            raise ConnectionError(f"{self.provider} not reachable at {self.base_url}")
        except Exception as e:
            status = "error"
            error_msg = str(e)[:500]
            raise

        latency_ms = int((time.monotonic() - start) * 1000)

        # Auto-track in TokenOps
        if self.ops:
            self.ops.log(
                model=f"{self.provider}/{model}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                agent=agent or self.default_agent or "local-llm",
                provider=self.provider,
                is_local=True,
                latency_ms=latency_ms,
                status=status,
                error_msg=error_msg,
                metadata=metadata,
            )

        return LocalResponse(
            content=content,
            model=model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw=data,
        )

    # ─── Generate (text completion, non-chat) ────────────

    def generate(
        self,
        model: str,
        prompt: str,
        agent: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LocalResponse:
        """Text completion (non-chat). Mainly for Ollama's /api/generate."""
        start = time.monotonic()

        if self.provider == "ollama":
            r = self._client.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            )
            r.raise_for_status()
            data = r.json()
            content = data.get("response", "")
            input_tokens = data.get("prompt_eval_count", 0)
            output_tokens = data.get("eval_count", 0)
        else:
            # Wrap as chat for OpenAI-compatible endpoints
            return self.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                agent=agent,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        latency_ms = int((time.monotonic() - start) * 1000)

        if self.ops:
            self.ops.log(
                model=f"{self.provider}/{model}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                agent=agent or self.default_agent or "local-llm",
                provider=self.provider,
                is_local=True,
                latency_ms=latency_ms,
            )

        return LocalResponse(
            content=content, model=model, provider=self.provider,
            input_tokens=input_tokens, output_tokens=output_tokens,
            latency_ms=latency_ms, raw=data,
        )

    # ─── Pull model (Ollama only) ────────────────────────

    def pull_model(self, model: str) -> bool:
        """Pull/download a model (Ollama only)."""
        if self.provider != "ollama":
            raise NotImplementedError("pull_model only supported for Ollama")
        try:
            r = self._client.post("/api/pull", json={"name": model, "stream": False})
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Failed to pull {model}: {e}")
            return False

    # ─── Cleanup ─────────────────────────────────────────

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
