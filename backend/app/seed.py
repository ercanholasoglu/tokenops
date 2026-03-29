"""
backend/app/seed.py
Seeds the ModelPricing table with current prices for all API types.
"""
from sqlalchemy.orm import Session
from sqlalchemy import select
from .models import ModelPricing

PRICING_DATA = [
    # ── LLM: Anthropic ──
    {"model": "claude-opus-4-5",    "provider": "Anthropic", "api_type": "llm", "input_per_1m": 15.00, "output_per_1m": 75.00, "context_window": 200000},
    {"model": "claude-sonnet-4-5",  "provider": "Anthropic", "api_type": "llm", "input_per_1m": 3.00,  "output_per_1m": 15.00, "context_window": 200000},
    {"model": "claude-haiku-4-5",   "provider": "Anthropic", "api_type": "llm", "input_per_1m": 0.25,  "output_per_1m": 1.25,  "context_window": 200000},
    # ── LLM: OpenAI ──
    {"model": "gpt-4o",             "provider": "OpenAI",    "api_type": "llm", "input_per_1m": 2.50,  "output_per_1m": 10.00, "context_window": 128000},
    {"model": "gpt-4o-mini",        "provider": "OpenAI",    "api_type": "llm", "input_per_1m": 0.15,  "output_per_1m": 0.60,  "context_window": 128000},
    {"model": "o1",                 "provider": "OpenAI",    "api_type": "llm", "input_per_1m": 15.00, "output_per_1m": 60.00, "context_window": 128000},
    {"model": "o1-mini",            "provider": "OpenAI",    "api_type": "llm", "input_per_1m": 3.00,  "output_per_1m": 12.00, "context_window": 128000},
    # ── LLM: Google ──
    {"model": "gemini-1.5-pro",     "provider": "Google",    "api_type": "llm", "input_per_1m": 1.25,  "output_per_1m": 5.00,  "context_window": 2000000},
    {"model": "gemini-1.5-flash",   "provider": "Google",    "api_type": "llm", "input_per_1m": 0.075, "output_per_1m": 0.30,  "context_window": 1000000},
    {"model": "gemini-2.0-flash",   "provider": "Google",    "api_type": "llm", "input_per_1m": 0.10,  "output_per_1m": 0.40,  "context_window": 1000000},
    # ── LLM: Groq ──
    {"model": "llama-3.1-70b",      "provider": "Groq",      "api_type": "llm", "input_per_1m": 0.59,  "output_per_1m": 0.79,  "context_window": 128000},
    {"model": "llama-3.1-8b",       "provider": "Groq",      "api_type": "llm", "input_per_1m": 0.05,  "output_per_1m": 0.08,  "context_window": 128000},
    {"model": "mixtral-8x7b",       "provider": "Groq",      "api_type": "llm", "input_per_1m": 0.24,  "output_per_1m": 0.24,  "context_window": 32000},
    # ── LLM: Mistral ──
    {"model": "mistral-large",      "provider": "Mistral",   "api_type": "llm", "input_per_1m": 2.00,  "output_per_1m": 6.00,  "context_window": 128000},
    {"model": "mistral-small",      "provider": "Mistral",   "api_type": "llm", "input_per_1m": 0.20,  "output_per_1m": 0.60,  "context_window": 32000},
    {"model": "mistral-nemo",       "provider": "Mistral",   "api_type": "llm", "input_per_1m": 0.15,  "output_per_1m": 0.15,  "context_window": 128000},
    # ── LLM: Cohere ──
    {"model": "command-r-plus",     "provider": "Cohere",    "api_type": "llm", "input_per_1m": 2.50,  "output_per_1m": 10.00, "context_window": 128000},
    {"model": "command-r",          "provider": "Cohere",    "api_type": "llm", "input_per_1m": 0.15,  "output_per_1m": 0.60,  "context_window": 128000},
    # ── LLM: Local (no cost, token tracking only) ──
    {"model": "ollama/llama3.1",    "provider": "Local",     "api_type": "llm", "input_per_1m": 0.0,   "output_per_1m": 0.0,   "context_window": 128000},
    {"model": "ollama/mistral",     "provider": "Local",     "api_type": "llm", "input_per_1m": 0.0,   "output_per_1m": 0.0,   "context_window": 32000},
    {"model": "vllm/llama-70b",     "provider": "Local",     "api_type": "llm", "input_per_1m": 0.0,   "output_per_1m": 0.0,   "context_window": 128000},
    {"model": "lmstudio/mixtral",   "provider": "Local",     "api_type": "llm", "input_per_1m": 0.0,   "output_per_1m": 0.0,   "context_window": 32000},
    # ── Video Generation ──
    {"model": "sora",               "provider": "OpenAI",    "api_type": "video", "cost_per_unit": 0.15,  "unit_label": "second"},
    {"model": "runway-gen3",        "provider": "Runway",    "api_type": "video", "cost_per_unit": 0.05,  "unit_label": "second"},
    {"model": "runway-gen3-turbo",  "provider": "Runway",    "api_type": "video", "cost_per_unit": 0.025, "unit_label": "second"},
    {"model": "kling-1.5",         "provider": "Kling",     "api_type": "video", "cost_per_unit": 0.04,  "unit_label": "second"},
    {"model": "pika-2.0",          "provider": "Pika",      "api_type": "video", "cost_per_unit": 0.08,  "unit_label": "second"},
    {"model": "minimax-video-01",  "provider": "MiniMax",   "api_type": "video", "cost_per_unit": 0.03,  "unit_label": "second"},
    # ── Image Generation ──
    {"model": "dall-e-3",           "provider": "OpenAI",    "api_type": "image", "cost_per_unit": 0.04,  "unit_label": "image"},
    {"model": "dall-e-3-hd",       "provider": "OpenAI",    "api_type": "image", "cost_per_unit": 0.08,  "unit_label": "image"},
    {"model": "stable-diffusion-3", "provider": "Stability", "api_type": "image", "cost_per_unit": 0.065, "unit_label": "image"},
    {"model": "midjourney-v6",      "provider": "Midjourney","api_type": "image", "cost_per_unit": 0.01,  "unit_label": "image"},
    {"model": "flux-1.1-pro",      "provider": "Black Forest","api_type": "image","cost_per_unit": 0.04, "unit_label": "image"},
    {"model": "ideogram-v2",       "provider": "Ideogram",  "api_type": "image", "cost_per_unit": 0.08,  "unit_label": "image"},
    # ── Audio / TTS / STT ──
    {"model": "whisper-1",          "provider": "OpenAI",    "api_type": "audio", "cost_per_unit": 0.006, "unit_label": "minute"},
    {"model": "tts-1",             "provider": "OpenAI",    "api_type": "audio", "cost_per_unit": 15.00, "unit_label": "1M_chars"},
    {"model": "tts-1-hd",          "provider": "OpenAI",    "api_type": "audio", "cost_per_unit": 30.00, "unit_label": "1M_chars"},
    {"model": "elevenlabs-v2",     "provider": "ElevenLabs","api_type": "audio", "cost_per_unit": 0.30,  "unit_label": "1K_chars"},
    # ── Embeddings ──
    {"model": "text-embedding-3-large", "provider": "OpenAI", "api_type": "embedding", "input_per_1m": 0.13, "output_per_1m": 0.0, "context_window": 8191},
    {"model": "text-embedding-3-small", "provider": "OpenAI", "api_type": "embedding", "input_per_1m": 0.02, "output_per_1m": 0.0, "context_window": 8191},
    {"model": "voyage-3",              "provider": "Voyage",  "api_type": "embedding", "input_per_1m": 0.06, "output_per_1m": 0.0, "context_window": 32000},
]


def seed_pricing(db: Session) -> int:
    """Insert or update model pricing. Returns count of new rows."""
    count = 0
    for row in PRICING_DATA:
        existing = db.execute(
            select(ModelPricing).where(ModelPricing.model == row["model"])
        ).scalar_one_or_none()
        if existing:
            for k, v in row.items():
                setattr(existing, k, v)
        else:
            db.add(ModelPricing(**row))
            count += 1
    db.commit()
    return count
