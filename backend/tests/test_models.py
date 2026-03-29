"""
backend/tests/test_models.py
Tests for enterprise database models.
"""
import os
os.environ["DATABASE_URL"] = "sqlite:///./test_enterprise.db"
os.environ["SECRET_KEY"] = "test-secret-key-enterprise-32chars!"
os.environ["ENVIRONMENT"] = "development"

import pytest
from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Team, Project, ApiKey, LLMCall, BudgetAlert,
    ModelPricing, LocalInstance, ProviderKey, AuditLog,
    gen_uuid,
)


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite:///./test_enterprise.db", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    os.remove("test_enterprise.db")


class TestTeam:
    def test_create_team(self, db):
        team = Team(name="Acme Corp", slug="acme", plan="enterprise", max_projects=20)
        db.add(team)
        db.commit()
        assert team.id is not None
        assert team.plan == "enterprise"
        assert team.max_projects == 20
        assert team.active is True

    def test_team_defaults(self, db):
        team = Team(name="Startup", slug="startup")
        db.add(team)
        db.commit()
        assert team.plan == "free"
        assert team.max_projects == 5
        assert team.max_monthly_budget == 500.0


class TestProject:
    def test_create_project_with_team(self, db):
        team = db.execute(select(Team).where(Team.slug == "acme")).scalar_one()
        project = Project(
            name="ML Pipeline", slug="ml-pipeline",
            team_id=team.id, budget=200.0, color="#3b82f6",
        )
        db.add(project)
        db.commit()
        assert project.team_id == team.id
        assert project.budget == 200.0

    def test_create_project_without_team(self, db):
        project = Project(name="Solo Project", slug="solo-proj")
        db.add(project)
        db.commit()
        assert project.team_id is None


class TestLLMCall:
    def test_cloud_call(self, db):
        project = db.execute(select(Project).where(Project.slug == "ml-pipeline")).scalar_one()
        call = LLMCall(
            project_id=project.id,
            model="claude-sonnet-4-5", provider="anthropic",
            api_type="llm", is_local=False,
            input_tokens=1500, output_tokens=800,
            cost_usd=0.0165, latency_ms=2400,
        )
        db.add(call)
        db.commit()
        assert call.is_local is False
        assert call.cost_usd == 0.0165

    def test_local_call(self, db):
        project = db.execute(select(Project).where(Project.slug == "ml-pipeline")).scalar_one()
        call = LLMCall(
            project_id=project.id,
            model="ollama/llama3.1", provider="ollama",
            api_type="llm", is_local=True,
            input_tokens=2000, output_tokens=1200,
            cost_usd=0.0, latency_ms=1800,
        )
        db.add(call)
        db.commit()
        assert call.is_local is True
        assert call.cost_usd == 0.0

    def test_video_call(self, db):
        project = db.execute(select(Project).where(Project.slug == "ml-pipeline")).scalar_one()
        call = LLMCall(
            project_id=project.id,
            model="runway-gen3", provider="runway",
            api_type="video", is_local=False,
            duration_sec=8.5, resolution="1080p",
            cost_usd=0.425, latency_ms=45000,
        )
        db.add(call)
        db.commit()
        assert call.api_type == "video"
        assert call.duration_sec == 8.5

    def test_call_status_types(self, db):
        project = db.execute(select(Project).where(Project.slug == "ml-pipeline")).scalar_one()
        for status in ["ok", "error", "timeout"]:
            call = LLMCall(
                project_id=project.id,
                model="gpt-4o", provider="openai",
                status=status, error_msg="test error" if status != "ok" else None,
            )
            db.add(call)
        db.commit()


class TestLocalInstance:
    def test_register_ollama(self, db):
        instance = LocalInstance(
            provider="ollama",
            base_url="http://localhost:11434",
            label="Dev Ollama",
            status="online",
            latency_ms=12,
            models_json='[{"name": "llama3.1"}, {"name": "mistral"}]',
        )
        db.add(instance)
        db.commit()
        assert instance.provider == "ollama"
        assert instance.status == "online"

    def test_register_lmstudio(self, db):
        instance = LocalInstance(
            provider="lmstudio",
            base_url="http://localhost:1234",
            label="LM Studio",
            status="offline",
        )
        db.add(instance)
        db.commit()
        assert instance.status == "offline"

    def test_register_vllm(self, db):
        instance = LocalInstance(
            provider="vllm",
            base_url="http://gpu-server:8001",
            label="Production vLLM",
            status="online",
            latency_ms=8,
        )
        db.add(instance)
        db.commit()
        assert instance.base_url == "http://gpu-server:8001"


class TestModelPricing:
    def test_cloud_model_pricing(self, db):
        pricing = ModelPricing(
            model="claude-sonnet-4-5", provider="Anthropic",
            api_type="llm", is_local=False,
            input_per_1m=3.0, output_per_1m=15.0,
            context_window=200000,
        )
        db.add(pricing)
        db.commit()
        assert pricing.is_local is False
        assert pricing.input_per_1m == 3.0

    def test_local_model_pricing(self, db):
        pricing = ModelPricing(
            model="ollama/llama3.1", provider="Local",
            api_type="llm", is_local=True,
            input_per_1m=0.0, output_per_1m=0.0,
            context_window=128000,
        )
        db.add(pricing)
        db.commit()
        assert pricing.is_local is True
        assert pricing.input_per_1m == 0.0

    def test_video_model_pricing(self, db):
        pricing = ModelPricing(
            model="sora", provider="OpenAI",
            api_type="video", is_local=False,
            cost_per_unit=0.15, unit_label="second",
        )
        db.add(pricing)
        db.commit()
        assert pricing.cost_per_unit == 0.15
        assert pricing.unit_label == "second"


class TestAuditLog:
    def test_create_audit_entry(self, db):
        log = AuditLog(
            action="project.create",
            entity_type="project",
            entity_id="test-id",
            details='{"name": "Test Project"}',
            ip_address="192.168.1.1",
        )
        db.add(log)
        db.commit()
        assert log.action == "project.create"
        assert log.created_at is not None

    def test_audit_actions(self, db):
        actions = [
            "key.generate", "key.revoke", "budget.update",
            "instance.register", "team.create",
        ]
        for action in actions:
            log = AuditLog(action=action, entity_type="test")
            db.add(log)
        db.commit()
        logs = db.execute(select(AuditLog)).scalars().all()
        assert len(logs) >= 6


class TestGenUUID:
    def test_uuid_format(self):
        uid = gen_uuid()
        assert isinstance(uid, str)
        assert len(uid) == 36  # standard UUID format
        assert uid.count("-") == 4

    def test_uuid_uniqueness(self):
        uuids = {gen_uuid() for _ in range(100)}
        assert len(uuids) == 100
