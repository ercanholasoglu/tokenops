"""
backend/app/models.py — Enterprise TokenOps Database Models

Tables:
  Project, ApiKey, LLMCall, BudgetAlert, ModelPricing  (existing, enhanced)
  LocalInstance    — Registered local LLM instances (Ollama, LM Studio, vLLM)
  ProviderKey      — External API key health monitoring
  Team             — Enterprise team management
  AuditLog         — All actions logged for compliance
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, DateTime,
    Boolean, ForeignKey, Text, Index
)
from sqlalchemy.orm import relationship
from .database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════
# CORE TABLES
# ═══════════════════════════════════════════════════════════

class Team(Base):
    """Enterprise team grouping for projects."""
    __tablename__ = "teams"

    id         = Column(String, primary_key=True, default=gen_uuid)
    name       = Column(String(100), nullable=False)
    slug       = Column(String(100), unique=True, nullable=False)
    plan       = Column(String(20), default="free")  # free, pro, enterprise
    max_projects = Column(Integer, default=5)
    max_monthly_budget = Column(Float, default=500.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    active     = Column(Boolean, default=True)

    projects = relationship("Project", back_populates="team")


class Project(Base):
    __tablename__ = "projects"

    id         = Column(String, primary_key=True, default=gen_uuid)
    team_id    = Column(String, ForeignKey("teams.id"), nullable=True)
    name       = Column(String(100), nullable=False)
    slug       = Column(String(100), unique=True, nullable=False)
    color      = Column(String(7), default="#f59e0b")
    budget     = Column(Float, default=100.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    active     = Column(Boolean, default=True)

    team      = relationship("Team", back_populates="projects")
    api_keys  = relationship("ApiKey", back_populates="project")
    calls     = relationship("LLMCall", back_populates="project")
    alerts    = relationship("BudgetAlert", back_populates="project")
    provider_keys = relationship("ProviderKey", back_populates="project")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id         = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    key_hash   = Column(String, unique=True, nullable=False)
    prefix     = Column(String(12), nullable=False)
    label      = Column(String(100), default="Default")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used  = Column(DateTime, nullable=True)
    active     = Column(Boolean, default=True)

    project = relationship("Project", back_populates="api_keys")


class LLMCall(Base):
    """Core tracking table — one row per API call."""
    __tablename__ = "llm_calls"

    id            = Column(String, primary_key=True, default=gen_uuid)
    project_id    = Column(String, ForeignKey("projects.id"), nullable=False)
    agent         = Column(String(100), nullable=True)
    model         = Column(String(100), nullable=False)
    provider      = Column(String(50), nullable=False)
    api_type      = Column(String(20), default="llm")
    is_local      = Column(Boolean, default=False)
    input_tokens  = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd      = Column(Float, default=0.0)
    latency_ms    = Column(Integer, default=0)
    status        = Column(String(10), default="ok")
    error_msg     = Column(Text, nullable=True)
    duration_sec  = Column(Float, nullable=True)
    resolution    = Column(String(20), nullable=True)
    file_size_mb  = Column(Float, nullable=True)
    unit_count    = Column(Integer, nullable=True)
    unit_label    = Column(String(50), nullable=True)
    metadata_     = Column("metadata", Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, index=True)

    project = relationship("Project", back_populates="calls")

    __table_args__ = (
        Index("ix_calls_project_created", "project_id", "created_at"),
        Index("ix_calls_model", "model"),
        Index("ix_calls_provider", "provider"),
        Index("ix_calls_api_type", "api_type"),
        Index("ix_calls_is_local", "is_local"),
    )


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"

    id          = Column(String, primary_key=True, default=gen_uuid)
    project_id  = Column(String, ForeignKey("projects.id"), nullable=False)
    threshold   = Column(Float, nullable=False)
    notified    = Column(Boolean, default=False)
    notified_at = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="alerts")


class ModelPricing(Base):
    """Pricing registry — all API types."""
    __tablename__ = "model_pricing"

    id              = Column(String, primary_key=True, default=gen_uuid)
    model           = Column(String(100), unique=True, nullable=False)
    provider        = Column(String(50), nullable=False)
    api_type        = Column(String(20), default="llm")
    input_per_1m    = Column(Float, nullable=True)
    output_per_1m   = Column(Float, nullable=True)
    cost_per_unit   = Column(Float, nullable=True)
    unit_label      = Column(String(50), nullable=True)
    context_window  = Column(Integer, default=0)
    is_local        = Column(Boolean, default=False)
    updated_at      = Column(DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════════
# LOCAL LLM INSTANCES
# ═══════════════════════════════════════════════════════════

class LocalInstance(Base):
    """Registered local LLM runtime instance."""
    __tablename__ = "local_instances"

    id           = Column(String, primary_key=True, default=gen_uuid)
    provider     = Column(String(30), nullable=False)  # ollama, lmstudio, vllm, llamacpp, localai
    base_url     = Column(String(200), nullable=False)
    label        = Column(String(100), default="Default")
    status       = Column(String(20), default="unknown")  # online, offline, unknown
    latency_ms   = Column(Integer, default=0)
    models_json  = Column(Text, nullable=True)   # JSON array of model info
    last_checked = Column(DateTime, nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════════
# PROVIDER API KEYS (external)
# ═══════════════════════════════════════════════════════════

class ProviderKey(Base):
    __tablename__ = "provider_keys"

    id             = Column(String, primary_key=True, default=gen_uuid)
    project_id     = Column(String, ForeignKey("projects.id"), nullable=False)
    provider       = Column(String(50), nullable=False)
    label          = Column(String(100), default="Default")
    key_masked     = Column(String(20), nullable=False)
    key_encrypted  = Column(Text, nullable=False)
    api_type       = Column(String(20), default="llm")
    is_valid       = Column(Boolean, nullable=True)
    last_checked   = Column(DateTime, nullable=True)
    error_detail   = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="provider_keys")


# ═══════════════════════════════════════════════════════════
# AUDIT LOG (Enterprise)
# ═══════════════════════════════════════════════════════════

class AuditLog(Base):
    """Enterprise audit trail — tracks all admin actions."""
    __tablename__ = "audit_logs"

    id         = Column(String, primary_key=True, default=gen_uuid)
    action     = Column(String(50), nullable=False)   # project.create, key.generate, budget.update, etc.
    entity_type = Column(String(30), nullable=True)   # project, api_key, provider_key, etc.
    entity_id  = Column(String, nullable=True)
    details    = Column(Text, nullable=True)           # JSON
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
