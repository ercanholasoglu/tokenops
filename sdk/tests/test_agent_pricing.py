"""
tests/test_agent_analytics.py
Tests for agent-level analytics, project×agent cross-tab, dynamic pricing.
"""
import os, sys
os.environ["DATABASE_URL"] = "sqlite:///./test_analytics.db"
os.environ["SECRET_KEY"] = "test-secret-key-analytics-32chars!!"
os.environ["ENVIRONMENT"] = "development"

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Minimal database + model setup ────────────────────────
# We test the SQL aggregation logic directly, not through FastAPI

from unittest.mock import MagicMock

# Build a real SQLite DB with the models
DB_URL = "sqlite:///./test_analytics.db"


@pytest.fixture(scope="module")
def setup_db():
    """Create tables and seed test data."""
    engine = create_engine(DB_URL, echo=False)

    # Import from the project — we need the actual models
    # For standalone testing, recreate minimal models
    from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, ForeignKey
    from sqlalchemy.orm import declarative_base, relationship

    Base = declarative_base()

    class Project(Base):
        __tablename__ = "projects"
        id = Column(String, primary_key=True)
        name = Column(String(100))
        slug = Column(String(100), unique=True)
        color = Column(String(7), default="#f59e0b")
        budget = Column(Float, default=100.0)
        active = Column(Boolean, default=True)
        team_id = Column(String, nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)

    class LLMCall(Base):
        __tablename__ = "llm_calls"
        id = Column(String, primary_key=True)
        project_id = Column(String, ForeignKey("projects.id"))
        agent = Column(String(100), nullable=True)
        model = Column(String(100))
        provider = Column(String(50))
        api_type = Column(String(20), default="llm")
        is_local = Column(Boolean, default=False)
        input_tokens = Column(Integer, default=0)
        output_tokens = Column(Integer, default=0)
        cost_usd = Column(Float, default=0.0)
        latency_ms = Column(Integer, default=0)
        status = Column(String(10), default="ok")
        error_msg = Column(String, nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed projects
    session.add(Project(id="p1", name="ML Pipeline", slug="ml-pipe", color="#3b82f6", budget=200))
    session.add(Project(id="p2", name="Chatbot", slug="chatbot", color="#ef4444", budget=100))
    session.commit()

    # Seed calls — 3 agents across 2 projects
    now = datetime.utcnow()
    calls = [
        # Agent: scout (project: ML Pipeline, model: gpt-4o)
        LLMCall(id="c1", project_id="p1", agent="scout", model="gpt-4o", provider="openai",
                input_tokens=500, output_tokens=200, cost_usd=0.00325, latency_ms=1200, created_at=now),
        LLMCall(id="c2", project_id="p1", agent="scout", model="gpt-4o", provider="openai",
                input_tokens=800, output_tokens=400, cost_usd=0.006, latency_ms=1800, created_at=now - timedelta(days=1)),

        # Agent: writer (project: ML Pipeline, model: claude-sonnet-4-5)
        LLMCall(id="c3", project_id="p1", agent="writer", model="claude-sonnet-4-5", provider="anthropic",
                input_tokens=1000, output_tokens=2000, cost_usd=0.033, latency_ms=3500, created_at=now),

        # Agent: writer (project: Chatbot, model: claude-sonnet-4-5)
        LLMCall(id="c4", project_id="p2", agent="writer", model="claude-sonnet-4-5", provider="anthropic",
                input_tokens=600, output_tokens=1500, cost_usd=0.0243, latency_ms=2800, created_at=now),

        # Agent: local-dev (project: ML Pipeline, model: ollama/llama3.1, LOCAL)
        LLMCall(id="c5", project_id="p1", agent="local-dev", model="ollama/llama3.1", provider="ollama",
                is_local=True, input_tokens=2000, output_tokens=3000, cost_usd=0.0, latency_ms=4500, created_at=now),

        # Error call
        LLMCall(id="c6", project_id="p1", agent="scout", model="gpt-4o", provider="openai",
                input_tokens=0, output_tokens=0, cost_usd=0.0, latency_ms=50,
                status="error", error_msg="rate limit", created_at=now),
    ]
    session.add_all(calls)
    session.commit()

    yield session, LLMCall, Project

    session.close()
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_analytics.db"):
        os.remove("test_analytics.db")


class TestAgentAggregation:
    """Test the SQL aggregation logic that powers /analytics/agents."""

    def test_agent_count(self, setup_db):
        session, LLMCall, Project = setup_db
        from sqlalchemy import select, func
        result = session.execute(
            select(LLMCall.agent, func.count(LLMCall.id))
            .where(LLMCall.agent.isnot(None))
            .group_by(LLMCall.agent)
        ).all()
        agents = {r[0]: r[1] for r in result}
        assert agents["scout"] == 3      # 2 ok + 1 error
        assert agents["writer"] == 2
        assert agents["local-dev"] == 1

    def test_agent_token_totals(self, setup_db):
        session, LLMCall, _ = setup_db
        from sqlalchemy import select, func
        result = session.execute(
            select(
                LLMCall.agent,
                func.sum(LLMCall.input_tokens).label("inp"),
                func.sum(LLMCall.output_tokens).label("out"),
            )
            .where(LLMCall.agent == "scout")
            .group_by(LLMCall.agent)
        ).first()
        assert result.inp == 1300   # 500 + 800 + 0 (error)
        assert result.out == 600    # 200 + 400 + 0

    def test_agent_cost_totals(self, setup_db):
        session, LLMCall, _ = setup_db
        from sqlalchemy import select, func
        result = session.execute(
            select(func.sum(LLMCall.cost_usd))
            .where(LLMCall.agent == "writer")
        ).scalar()
        assert round(result, 4) == round(0.033 + 0.0243, 4)

    def test_local_vs_cloud(self, setup_db):
        session, LLMCall, _ = setup_db
        from sqlalchemy import select, func, case
        result = session.execute(
            select(
                func.sum(case((LLMCall.is_local == True, 1), else_=0)).label("local"),
                func.sum(case((LLMCall.is_local == False, 1), else_=0)).label("cloud"),
            )
            .where(LLMCall.agent == "local-dev")
        ).first()
        assert result.local == 1
        assert result.cloud == 0

    def test_error_count(self, setup_db):
        session, LLMCall, _ = setup_db
        from sqlalchemy import select, func, case
        result = session.execute(
            select(
                func.sum(case((LLMCall.status == "error", 1), else_=0))
            )
            .where(LLMCall.agent == "scout")
        ).scalar()
        assert result == 1


class TestProjectAgentCrossTab:
    """Test the project × agent cross-tabulation logic."""

    def test_cross_tab_rows(self, setup_db):
        session, LLMCall, Project = setup_db
        from sqlalchemy import select, func
        result = session.execute(
            select(
                LLMCall.project_id,
                LLMCall.agent,
                func.count(LLMCall.id).label("calls"),
                func.sum(LLMCall.cost_usd).label("cost"),
            )
            .where(LLMCall.agent.isnot(None))
            .group_by(LLMCall.project_id, LLMCall.agent)
        ).all()

        cross = {(r.project_id, r.agent): r for r in result}

        # writer in p1 and p2
        assert ("p1", "writer") in cross
        assert ("p2", "writer") in cross
        assert cross[("p1", "writer")].calls == 1
        assert cross[("p2", "writer")].calls == 1

        # scout only in p1
        assert ("p1", "scout") in cross
        assert ("p2", "scout") not in cross

    def test_project_totals(self, setup_db):
        session, LLMCall, _ = setup_db
        from sqlalchemy import select, func
        result = session.execute(
            select(
                LLMCall.project_id,
                func.sum(LLMCall.cost_usd).label("cost"),
                func.sum(LLMCall.input_tokens + LLMCall.output_tokens).label("tokens"),
            )
            .where(LLMCall.agent.isnot(None))
            .group_by(LLMCall.project_id)
        ).all()
        totals = {r.project_id: r for r in result}
        # p1 has scout + writer + local-dev
        assert totals["p1"].tokens == (500+200) + (800+400) + (1000+2000) + (2000+3000) + (0+0)
        # p2 has writer only
        assert totals["p2"].tokens == 600 + 1500

    def test_agent_totals_across_projects(self, setup_db):
        session, LLMCall, _ = setup_db
        from sqlalchemy import select, func
        result = session.execute(
            select(
                LLMCall.agent,
                func.sum(LLMCall.cost_usd).label("cost"),
            )
            .where(LLMCall.agent.isnot(None))
            .group_by(LLMCall.agent)
            .order_by(func.sum(LLMCall.cost_usd).desc())
        ).all()
        agent_costs = {r.agent: round(r.cost, 6) for r in result}
        # writer is most expensive (0.033 + 0.0243 = 0.0573)
        assert agent_costs["writer"] == round(0.033 + 0.0243, 6)
        # local-dev costs $0
        assert agent_costs["local-dev"] == 0.0


class TestDynamicPricing:
    """Test the 3-tier pricing engine."""

    def test_fallback_pricing_known_model(self):
        from tokenops.pricing import compute_cost
        # gpt-4o: $2.5 input, $10 output per 1M
        cost = compute_cost("gpt-4o", 1_000_000, 0)
        assert cost == 2.5

    def test_fallback_pricing_output(self):
        from tokenops.pricing import compute_cost
        cost = compute_cost("gpt-4o", 0, 1_000_000)
        assert cost == 10.0

    def test_fallback_pricing_combined(self):
        from tokenops.pricing import compute_cost
        # claude-sonnet-4-5: $3 input, $15 output
        cost = compute_cost("claude-sonnet-4-5", 1000, 500)
        expected = (1000 / 1e6) * 3.0 + (500 / 1e6) * 15.0
        assert abs(cost - expected) < 0.0001

    def test_unknown_model_zero_cost(self):
        from tokenops.pricing import compute_cost
        cost = compute_cost("totally-unknown-model-xyz", 1000, 1000)
        assert cost == 0.0

    def test_local_model_zero_cost(self):
        from tokenops.pricing import compute_cost
        cost = compute_cost("ollama/llama3.1", 50000, 50000)
        # Not in fallback, should be 0
        assert cost == 0.0

    def test_get_provider_known(self):
        from tokenops.pricing import get_provider
        assert get_provider("claude-sonnet-4-5") == "anthropic"
        assert get_provider("gpt-4o") == "openai"
        assert get_provider("gemini-2.0-flash") == "google"
        assert get_provider("deepseek-chat") == "deepseek"

    def test_get_provider_inference(self):
        from tokenops.pricing import get_provider
        assert get_provider("claude-opus-99") == "anthropic"
        assert get_provider("gpt-5-turbo") == "openai"
        assert get_provider("ollama/phi-3") == "ollama"
        assert get_provider("groq/llama-3") == "groq"

    def test_get_api_type(self):
        from tokenops.pricing import get_api_type
        assert get_api_type("text-embedding-3-small") == "embedding"
        assert get_api_type("gpt-4o") == "llm"
        assert get_api_type("tts-1") == "audio"
        assert get_api_type("dall-e-3") == "image"

    def test_pricing_engine_standalone(self):
        from tokenops.pricing import PricingEngine
        engine = PricingEngine()  # no backend
        cost = engine.compute("gpt-4o-mini", 10000, 5000)
        expected = (10000 / 1e6) * 0.15 + (5000 / 1e6) * 0.6
        assert abs(cost - expected) < 0.0001

    def test_pricing_engine_lookup(self):
        from tokenops.pricing import PricingEngine
        engine = PricingEngine()
        p = engine.lookup("claude-opus-4")
        assert p["input"] == 15.0
        assert p["output"] == 75.0

    def test_litellm_fallback(self):
        """If litellm is installed, it should find models not in hardcoded list."""
        from tokenops.pricing import _litellm_lookup
        result = _litellm_lookup("gpt-4o")
        # litellm might or might not be installed in test env
        # If installed, result should have input/output
        # If not installed, result should be None
        if result is not None:
            assert "input" in result
            assert "output" in result
            assert result["input"] > 0
