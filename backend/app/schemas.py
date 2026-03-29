"""
backend/app/schemas.py — Enterprise Pydantic schemas.
Adds: LocalInstance, LocalDiscovery, Team, AuditLog schemas.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Existing schemas (enhanced) ──────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    color: str = Field(default="#f59e0b", pattern=r"^#[0-9a-fA-F]{6}$")
    budget: float = Field(default=100.0, gt=0)
    team_id: Optional[str] = None

class ProjectOut(BaseModel):
    id: str
    name: str
    slug: str
    color: str
    budget: float
    team_id: Optional[str]
    created_at: datetime
    active: bool
    model_config = {"from_attributes": True}

class CallCreate(BaseModel):
    agent: Optional[str] = None
    model: str
    provider: str
    api_type: str = Field(default="llm")
    is_local: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Optional[float] = None
    latency_ms: int = Field(default=0, ge=0)
    status: str = Field(default="ok", pattern=r"^(ok|error|timeout)$")
    error_msg: Optional[str] = None
    duration_sec: Optional[float] = None
    resolution: Optional[str] = None
    file_size_mb: Optional[float] = None
    unit_count: Optional[int] = None
    unit_label: Optional[str] = None
    metadata: Optional[dict] = None

class CallOut(BaseModel):
    id: str
    project_id: str
    agent: Optional[str]
    model: str
    provider: str
    api_type: str
    is_local: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    status: str
    error_msg: Optional[str]
    duration_sec: Optional[float]
    resolution: Optional[str]
    file_size_mb: Optional[float]
    unit_count: Optional[int]
    unit_label: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}

class ModelPricingOut(BaseModel):
    model: str
    provider: str
    api_type: str
    input_per_1m: Optional[float]
    output_per_1m: Optional[float]
    cost_per_unit: Optional[float]
    unit_label: Optional[str]
    context_window: int
    is_local: bool
    model_config = {"from_attributes": True}


# ── Dashboard schemas ─────────────────────────────────────

class DailyPoint(BaseModel):
    date: str
    cost: float
    calls: int
    tokens: int

class ProviderBreakdown(BaseModel):
    provider: str
    cost: float
    calls: int
    tokens: int
    pct: float

class ApiTypeBreakdown(BaseModel):
    api_type: str
    cost: float
    calls: int
    tokens: int
    pct: float

class ModelStat(BaseModel):
    model: str
    provider: str
    api_type: str
    is_local: bool
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    avg_latency_ms: float

class ProjectStats(BaseModel):
    project_id: str
    project_name: str
    color: str
    total_cost: float
    budget: float
    budget_pct: float
    total_calls: int
    total_tokens: int
    top_model: Optional[str]
    api_types_used: list[str]
    local_calls: int
    cloud_calls: int

class LocalLLMStats(BaseModel):
    model: str
    provider: str
    calls: int
    input_tokens: int
    output_tokens: int
    avg_latency_ms: float

class AgentStats(BaseModel):
    agent: str
    calls: int
    cost: float
    tokens: int
    top_model: Optional[str]
    error_rate: float

class HourlyActivity(BaseModel):
    hour: int
    calls: int
    cost: float
    tokens: int

class CostForecast(BaseModel):
    date: str
    predicted_cost: float
    lower_bound: float
    upper_bound: float

class DashboardOverview(BaseModel):
    total_cost_month: float
    total_tokens_month: int
    total_calls_month: int
    avg_cost_per_call: float
    cost_trend_pct: float
    daily_breakdown: list[DailyPoint]
    provider_breakdown: list[ProviderBreakdown]
    api_type_breakdown: list[ApiTypeBreakdown]
    model_stats: list[ModelStat]
    project_stats: list[ProjectStats]
    local_llm_stats: list[LocalLLMStats]
    agent_stats: list[AgentStats]
    hourly_activity: list[HourlyActivity]
    error_rate: float
    total_local_calls: int
    total_local_tokens: int
    cost_forecast: list[CostForecast] = []


# ── Local LLM schemas ─────────────────────────────────────

class LocalModelInfo(BaseModel):
    name: str
    size: Optional[int] = 0
    family: Optional[str] = ""
    parameters: Optional[str] = ""
    quantization: Optional[str] = ""
    format: Optional[str] = ""

class LocalDiscoveryResult(BaseModel):
    provider: str
    name: str
    base_url: str
    status: str
    latency_ms: int
    models: list[dict]
    error: Optional[str]

class LocalInstanceOut(BaseModel):
    id: str
    provider: str
    base_url: str
    label: str
    status: str
    latency_ms: int
    models_json: Optional[str]
    last_checked: Optional[datetime]
    error_detail: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Provider Key schemas ──────────────────────────────────

class ProviderKeyCreate(BaseModel):
    provider: str
    label: str = "Default"
    api_key: str
    api_type: str = "llm"

class ProviderKeyOut(BaseModel):
    id: str
    project_id: str
    provider: str
    label: str
    key_masked: str
    api_type: str
    is_valid: Optional[bool]
    last_checked: Optional[datetime]
    error_detail: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}

class HealthCheckResult(BaseModel):
    provider: str
    is_valid: bool
    latency_ms: int
    error_detail: Optional[str]
    checked_at: datetime
    models_available: list[str] = []


# ── Team schemas (Enterprise) ─────────────────────────────

class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    plan: str = Field(default="free")
    max_projects: int = Field(default=5)
    max_monthly_budget: float = Field(default=500.0)

class TeamOut(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    max_projects: int
    max_monthly_budget: float
    created_at: datetime
    active: bool
    model_config = {"from_attributes": True}

class ProjectDetailAnalytics(BaseModel):
    project_id: str
    project_name: str
    total_cost: float
    budget: float
    budget_pct: float
    total_calls: int
    total_tokens: int
    daily_breakdown: list[DailyPoint]
    model_stats: list[ModelStat]
    agent_stats: list[AgentStats]
    api_type_breakdown: list[ApiTypeBreakdown]
    hourly_activity: list[HourlyActivity]
    error_rate: float
    avg_latency_ms: float
    local_calls: int
    cloud_calls: int
    cost_trend_pct: float
