"""
sdk/tokenops/middleware.py — Auto-tracking middleware.

Wraps popular LLM libraries so every call is automatically logged to TokenOps.
Zero code changes needed beyond one setup line.

Usage:
    from tokenops.middleware import patch_openai, patch_anthropic, patch_all

    # Patch individual libraries
    patch_openai(ops)      # Auto-tracks all openai.chat.completions.create()
    patch_anthropic(ops)   # Auto-tracks all anthropic.messages.create()

    # Or patch everything at once
    patch_all(ops)

    # Then use libraries normally — calls are auto-tracked
    response = openai_client.chat.completions.create(model="gpt-4o", ...)
    # ^ automatically logged to TokenOps
"""
import time
import functools
from typing import Optional, Callable
from loguru import logger


def patch_openai(ops, agent: Optional[str] = None):
    """
    Monkey-patch OpenAI SDK to auto-track all chat completions.
    Works with: openai.chat.completions.create() and openai.completions.create()

    Args:
        ops: TokenOps client instance
        agent: Default agent name for tracking
    """
    try:
        import openai
        _original_chat = openai.resources.chat.completions.Completions.create

        @functools.wraps(_original_chat)
        def _tracked_chat(self, *args, **kwargs):
            start = time.monotonic()
            status = "ok"
            error_msg = None
            response = None

            try:
                response = _original_chat(self, *args, **kwargs)
            except Exception as e:
                status = "error"
                error_msg = str(e)[:500]
                raise
            finally:
                latency_ms = int((time.monotonic() - start) * 1000)
                model = kwargs.get("model", getattr(response, "model", "unknown") if response else "unknown")
                usage = getattr(response, "usage", None) if response else None
                inp = getattr(usage, "prompt_tokens", 0) if usage else 0
                out = getattr(usage, "completion_tokens", 0) if usage else 0

                ops.log(
                    model=model,
                    input_tokens=inp,
                    output_tokens=out,
                    agent=agent or ops.default_agent or "openai-auto",
                    provider="openai",
                    latency_ms=latency_ms,
                    status=status,
                    error_msg=error_msg,
                )
            return response

        openai.resources.chat.completions.Completions.create = _tracked_chat
        logger.info("TokenOps: patched openai.chat.completions.create()")

    except ImportError:
        logger.debug("TokenOps: openai not installed, skipping patch")
    except Exception as e:
        logger.warning(f"TokenOps: failed to patch openai: {e}")


def patch_anthropic(ops, agent: Optional[str] = None):
    """
    Monkey-patch Anthropic SDK to auto-track all messages.

    Args:
        ops: TokenOps client instance
        agent: Default agent name
    """
    try:
        import anthropic
        _original = anthropic.resources.messages.Messages.create

        @functools.wraps(_original)
        def _tracked(self, *args, **kwargs):
            start = time.monotonic()
            status = "ok"
            error_msg = None
            response = None

            try:
                response = _original(self, *args, **kwargs)
            except Exception as e:
                status = "error"
                error_msg = str(e)[:500]
                raise
            finally:
                latency_ms = int((time.monotonic() - start) * 1000)
                model = kwargs.get("model", getattr(response, "model", "unknown") if response else "unknown")
                usage = getattr(response, "usage", None) if response else None
                inp = getattr(usage, "input_tokens", 0) if usage else 0
                out = getattr(usage, "output_tokens", 0) if usage else 0

                ops.log(
                    model=model,
                    input_tokens=inp,
                    output_tokens=out,
                    agent=agent or ops.default_agent or "anthropic-auto",
                    provider="anthropic",
                    latency_ms=latency_ms,
                    status=status,
                    error_msg=error_msg,
                )
            return response

        anthropic.resources.messages.Messages.create = _tracked
        logger.info("TokenOps: patched anthropic.messages.create()")

    except ImportError:
        logger.debug("TokenOps: anthropic not installed, skipping patch")
    except Exception as e:
        logger.warning(f"TokenOps: failed to patch anthropic: {e}")


def patch_litellm(ops, agent: Optional[str] = None):
    """
    Patch litellm.completion() — covers all providers through litellm.
    This is the most universal patch since litellm wraps everything.
    """
    try:
        import litellm
        _original = litellm.completion

        @functools.wraps(_original)
        def _tracked(*args, **kwargs):
            start = time.monotonic()
            status = "ok"
            error_msg = None
            response = None

            try:
                response = _original(*args, **kwargs)
            except Exception as e:
                status = "error"
                error_msg = str(e)[:500]
                raise
            finally:
                latency_ms = int((time.monotonic() - start) * 1000)
                model = kwargs.get("model", args[0] if args else "unknown")
                usage = getattr(response, "usage", None) if response else None
                inp = getattr(usage, "prompt_tokens", 0) if usage else 0
                out = getattr(usage, "completion_tokens", 0) if usage else 0

                # Detect provider from model string
                provider = "unknown"
                if "/" in str(model):
                    provider = str(model).split("/")[0]
                elif str(model).startswith("gpt") or str(model).startswith("o1"):
                    provider = "openai"
                elif str(model).startswith("claude"):
                    provider = "anthropic"

                ops.log(
                    model=str(model),
                    input_tokens=inp,
                    output_tokens=out,
                    agent=agent or ops.default_agent or "litellm-auto",
                    provider=provider,
                    latency_ms=latency_ms,
                    status=status,
                    error_msg=error_msg,
                )
            return response

        litellm.completion = _tracked
        logger.info("TokenOps: patched litellm.completion()")

    except ImportError:
        logger.debug("TokenOps: litellm not installed, skipping patch")
    except Exception as e:
        logger.warning(f"TokenOps: failed to patch litellm: {e}")


def patch_all(ops, agent: Optional[str] = None):
    """
    Patch all supported libraries at once.
    Call this once at app startup.

    Usage:
        from tokenops import TokenOps
        from tokenops.middleware import patch_all

        ops = TokenOps(api_key="tok_live_xxx")
        patch_all(ops)

        # Now all LLM calls are auto-tracked
    """
    patch_openai(ops, agent)
    patch_anthropic(ops, agent)
    patch_litellm(ops, agent)
    logger.info("TokenOps: all available libraries patched for auto-tracking")
