"""统一 LLM Client 与模型路由测试（Phase 3 任务书 12 节，全离线 Fake）。"""
from __future__ import annotations

import json

import pytest

from research_os.llm.client import LlmClient
from research_os.llm.models import LlmRequest
from research_os.llm.provider import FakeLlmProvider
from research_os.llm.routing import ModelRouter
from research_os.llm.validation import LlmOutputValidator
from research_os.storage import Database
from research_os.utils.id import new_uuid

VALID_OUTPUT = {
    "data_type": "news_flash",
    "requested_sources": ["cls"],
    "attempted_sources": ["cls"],
    "selected_source": "cls",
    "fallback_used": False,
    "status": "success",
    "missing_fields": [],
    "warnings": [],
}


def _req() -> LlmRequest:
    return LlmRequest(
        call_id=new_uuid(), task_id=new_uuid(), module="test", prompt="输出",
        prompt_hash="h1", output_schema_name="data_route",
    )


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "llm.db")
    database.initialize()
    yield database
    database.close()


class TestUnconfiguredClient:
    def test_honest_fallback_no_call(self, db):
        client = LlmClient(db=db, configured=False)
        resp = client.generate_json(_req(), {})
        assert resp.called is False
        assert resp.status == "fallback"
        assert resp.schema_valid is False
        assert any("未配置" in w for w in resp.warnings)
        assert db.count("llm_call_records") == 1


class TestConfiguredClient:
    def test_success_path(self, db):
        provider = FakeLlmProvider(outputs={"h1": VALID_OUTPUT})
        client = LlmClient(provider=provider, db=db, configured=True)
        resp = client.generate_json(_req(), {})
        assert resp.called is True
        assert resp.status == "success"
        assert resp.schema_valid is True
        assert resp.output["data_type"] == "news_flash"
        assert db.count("llm_call_records") == 1

    def test_invalid_json_then_fix_success(self, db):
        calls = {"n": 0}

        def behavior(req, schema):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"ok": True, "output": "not-json{{", "error": None, "model_id": "flash"}
            return {"ok": True, "output": VALID_OUTPUT, "error": None, "model_id": "flash"}

        client = LlmClient(provider=FakeLlmProvider(behavior=behavior), db=db, configured=True)
        resp = client.generate_json(_req(), {})
        assert resp.status == "success"
        assert resp.attempt_count == 2

    def test_flash_fails_twice_escalates_pro(self, db):
        """Flash 两次结构失败 -> 升级 Pro（业务升级，非 provider 故障）。"""
        models = []

        def behavior(req, schema):
            models.append(req.requested_model_class)
            if req.requested_model_class == "flash":
                return {"ok": True, "output": {"bad": 1}, "error": None, "model_id": "flash"}
            return {"ok": True, "output": VALID_OUTPUT, "error": None, "model_id": "pro"}

        client = LlmClient(provider=FakeLlmProvider(behavior=behavior), db=db, configured=True)
        resp = client.generate_json(_req(), {})
        assert models == ["flash", "flash", "pro"]
        assert resp.status == "success"
        assert resp.business_escalation_used is True
        assert resp.business_escalation_reason is not None
        assert resp.provider_fallback_used is False, "业务升级不得标记为 provider 故障"

    def test_all_fail_deterministic_fallback(self, db):
        provider = FakeLlmProvider(
            behavior=lambda req, schema: {"ok": True, "output": {"bad": 1},
                                           "error": None, "model_id": "flash"})
        client = LlmClient(provider=provider, db=db, configured=True)
        resp = client.generate_json(_req(), {})
        assert resp.called is True
        assert resp.status == "fallback"
        assert resp.schema_valid is False
        assert resp.validation_errors, "必须如实记录校验错误"

    def test_provider_failure_fallback_separated(self, db):
        """Provider 故障（抛异常）-> provider_fallback_used=True，与业务升级分离。"""
        provider = FakeLlmProvider(
            behavior=lambda req, schema: (_ for _ in ()).throw(RuntimeError("timeout")))
        client = LlmClient(provider=provider, db=db, configured=True)
        resp = client.generate_json(_req(), {})
        assert resp.called is True
        assert resp.status == "fallback"
        assert resp.provider_fallback_used is True
        assert resp.provider_fallback_reason is not None
        assert resp.business_escalation_used is False

    def test_max_one_pro_call(self, db):
        """Pro 也失败 -> 不循环调用。"""
        models = []

        def behavior(req, schema):
            models.append(req.requested_model_class)
            return {"ok": True, "output": {"bad": 1}, "error": None, "model_id": req.requested_model_class}

        client = LlmClient(provider=FakeLlmProvider(behavior=behavior), db=db, configured=True)
        resp = client.generate_json(_req(), {})
        assert models == ["flash", "flash", "pro"], f"调用序列: {models}"
        assert resp.status == "fallback"


class TestOutputValidator:
    def test_schema_validation(self):
        v = LlmOutputValidator()
        ok, parsed, errors = v.validate(VALID_OUTPUT, "data_route")
        assert ok is True
        assert parsed is not None

    def test_invalid_schema_rejected(self):
        v = LlmOutputValidator()
        ok, parsed, errors = v.validate({"data_type": 123}, "data_route")
        assert ok is False
        assert errors

    def test_non_dict_rejected(self):
        v = LlmOutputValidator()
        ok, parsed, errors = v.validate([1, 2], "data_route")
        assert ok is False


class TestModelRouter:
    def test_escalation_conditions(self):
        router = ModelRouter()
        assert router.should_escalate({"reasoning_conflict_count": 3}).escalate
        assert router.should_escalate({"high_authority_conflict": True}).escalate
        assert router.should_escalate({"supply_chain_hops": 4}).escalate
        assert router.should_escalate({"top2_score_gap": 5}).escalate
        assert router.should_escalate({"flash_schema_failures": 2}).escalate
        assert not router.should_escalate({}).escalate
        assert not router.should_escalate(
            {"reasoning_conflict_count": 2, "top2_score_gap": 9}).escalate

    def test_build_route_separates_failure_kinds(self):
        router = ModelRouter()
        route = router.build_route(
            llm_called=True, selected_model=None, failure_stage="schema_validation",
            limitation="semantic_attribution_unavailable",
            escalation_reasons=["top2 原因得分差<8"],
            business_escalation_reason="top2 原因得分差<8",
            provider_fallback_used=True,
            provider_fallback_reason="provider timeout",
        )
        assert route.mode == "deterministic_fallback"
        assert route.llm_called is True
        assert route.business_escalation_reason is not None
        assert route.provider_fallback_reason is not None
        assert route.provider_fallback_used is True
        assert route.escalated is True

    def test_build_route_no_call(self):
        router = ModelRouter()
        route = router.build_route(llm_called=False)
        assert route.mode == "deterministic_fallback"
        assert route.llm_called is False
