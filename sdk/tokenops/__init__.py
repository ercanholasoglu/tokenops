"""
tokenops — Enterprise LLM Cost Intelligence SDK

Core:
    from tokenops import TokenOps
    ops = TokenOps(api_key="tok_live_xxx")
    ops.log(model="gpt-4o", input_tokens=1000, output_tokens=500)

Auto-tracking middleware (1 line setup):
    from tokenops.middleware import patch_all
    patch_all(ops)  # auto-tracks all OpenAI, Anthropic, litellm calls

Local LLM (Ollama, LM Studio, vLLM):
    from tokenops.local import LocalLLM
    llm = LocalLLM(ops=ops, provider="ollama")
    response = llm.chat(model="llama3.1", messages=[...])
"""
from .client import TokenOps
from .pricing import compute_cost, compute_unit_cost, get_provider, get_api_type, PRICING
from .local import LocalLLM

__version__ = "1.0.0"
__all__ = [
    "TokenOps",
    "LocalLLM",
    "compute_cost",
    "compute_unit_cost",
    "get_provider",
    "get_api_type",
    "PRICING",
]
