"""sdk/tokenops/client.py — TokenOps main client (unchanged from v0.2)"""
import time
import functools
from contextlib import contextmanager
from typing import Optional, Callable
import httpx
from .pricing import compute_cost, get_provider

class TokenOps:
    def __init__(self, api_key: str, project: str = "default", base_url: str = "http://localhost:8000",
                 agent: Optional[str] = None, silent: bool = True, timeout: float = 5.0):
        self.api_key = api_key
        self.project = project
        self.base_url = base_url.rstrip("/")
        self.default_agent = agent
        self.silent = silent
        self._client = httpx.Client(base_url=self.base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)

    def log(self, model: str, input_tokens: int = 0, output_tokens: int = 0, agent: Optional[str] = None,
            provider: Optional[str] = None, api_type: str = "llm", is_local: bool = False,
            latency_ms: int = 0, cost_usd: Optional[float] = None, status: str = "ok",
            error_msg: Optional[str] = None, duration_sec: Optional[float] = None,
            resolution: Optional[str] = None, file_size_mb: Optional[float] = None,
            unit_count: Optional[int] = None, unit_label: Optional[str] = None,
            metadata: Optional[dict] = None) -> bool:
        inferred_provider = provider or get_provider(model)
        inferred_cost = 0.0 if is_local else (cost_usd if cost_usd is not None else compute_cost(model, input_tokens, output_tokens))
        payload = {"agent": agent or self.default_agent, "model": model, "provider": inferred_provider,
                   "api_type": api_type, "is_local": is_local, "input_tokens": input_tokens,
                   "output_tokens": output_tokens, "cost_usd": inferred_cost, "latency_ms": latency_ms,
                   "status": status, "error_msg": error_msg, "duration_sec": duration_sec,
                   "resolution": resolution, "file_size_mb": file_size_mb, "unit_count": unit_count,
                   "unit_label": unit_label, "metadata": metadata}
        return self._send(payload)

    def log_video(self, model: str, duration_sec: float, **kw) -> bool:
        return self.log(model=model, api_type="video", duration_sec=duration_sec,
                       unit_count=int(duration_sec), unit_label="seconds", **kw)

    def log_image(self, model: str, count: int = 1, **kw) -> bool:
        return self.log(model=model, api_type="image", unit_count=count, unit_label="images", **kw)

    def log_audio(self, model: str, **kw) -> bool:
        return self.log(model=model, api_type="audio", **kw)

    def log_embedding(self, model: str, input_tokens: int, **kw) -> bool:
        return self.log(model=model, api_type="embedding", input_tokens=input_tokens, **kw)

    def track(self, agent: Optional[str] = None, model_attr: str = "model", extract_tokens: Optional[Callable] = None):
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                start = time.monotonic()
                status, error_msg, response = "ok", None, None
                try:
                    response = fn(*args, **kwargs)
                except Exception as e:
                    status, error_msg = "error", str(e)[:500]
                    raise
                finally:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    model = kwargs.get(model_attr, "unknown")
                    inp, out = (0, 0) if response is None else _extract(response, extract_tokens)
                    self.log(model=model, input_tokens=inp, output_tokens=out,
                            agent=agent or self.default_agent, latency_ms=latency_ms, status=status, error_msg=error_msg)
                return response
            return wrapper
        return decorator

    @contextmanager
    def session(self, agent: Optional[str] = None):
        yield _Session(self, agent or self.default_agent)

    def _send(self, payload: dict) -> bool:
        try:
            r = self._client.post("/calls", json=payload)
            r.raise_for_status()
            return True
        except Exception:
            if not self.silent: raise
            return False

    def close(self): self._client.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

class _Session:
    def __init__(self, ops, agent): self._ops, self._agent, self._start = ops, agent, time.monotonic()
    def log(self, response, model=None, metadata=None):
        inp, out = _extract(response, None)
        self._ops.log(model=model or _model(response) or "unknown", input_tokens=inp, output_tokens=out,
                     agent=self._agent, latency_ms=int((time.monotonic()-self._start)*1000), metadata=metadata)

def _extract(resp, fn):
    if resp is None: return 0, 0
    if fn: return fn(resp)
    if hasattr(resp, "usage"):
        u = resp.usage
        return getattr(u,"input_tokens",0) or getattr(u,"prompt_tokens",0) or 0, getattr(u,"output_tokens",0) or getattr(u,"completion_tokens",0) or 0
    if isinstance(resp, dict):
        u = resp.get("usage",{})
        return u.get("prompt_tokens",0), u.get("completion_tokens",0)
    return 0, 0

def _model(resp):
    if resp is None: return None
    return getattr(resp,"model",None) or (resp.get("model") if isinstance(resp,dict) else None)
