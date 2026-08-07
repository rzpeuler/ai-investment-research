"""来源层单元测试（Phase 1 任务 11.1 节）。

覆盖：Source / SourceProbe / DataRoute 模型正常-边界-失败、
来源评分边界、访问状态枚举、URL 标准化、限速策略、SourceRegistry。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_os.collectors import RateLimitPolicy
from research_os.models import DataRoute, Source, SourceProbe
from research_os.source_registry import SourceRegistry
from research_os.utils.url import normalize_url, normalized_url_hash
from research_os.validators.schema_validator import validate_model

T0 = "2026-08-05T08:00:00"
UUID = "11111111-1111-1111-1111-111111111111"


def valid_source(**overrides) -> dict:
    data = {
        "source_id": "cninfo", "name": "巨潮资讯", "platform": "cninfo",
        "base_domain": "http://www.cninfo.com.cn", "source_type": "official_disclosure",
        "source_tier": "S",
        "authority_score": 5, "accuracy_score": 5, "timeliness_score": 4,
        "coverage_score": 5, "stability_score": 0, "originality_score": 5,
        "opinion_influence_score": 0,
        "access_level": "public", "automation_level": "html",
        "login_required": False, "paid": False,
        "storage_policy": "metadata_and_excerpt", "rate_limit": None,
        "update_frequency": "realtime", "allowed_usage": "公告元数据",
        "primary_topics": ["公告"], "status": "candidate",
        "last_verified_at": None, "verification_evidence": [],
        "notes": "",
    }
    data.update(overrides)
    return data


def valid_probe(**overrides) -> dict:
    data = {
        "probe_id": UUID, "source_id": "cninfo",
        "started_at": T0, "finished_at": T0,
        "status": "success", "http_status": 200,
        "access_level_detected": "public", "automation_level_detected": "html",
        "historical_depth": None, "fields_detected": ["title"],
        "requires_javascript": False, "requires_login": False,
        "rate_limit_observed": None,
        "storage_policy_recommendation": "metadata_and_excerpt",
        "evidence": [{"url": "http://x", "http_status": 200}],
        "errors": [], "notes": [],
    }
    data.update(overrides)
    return data


def valid_route(**overrides) -> dict:
    data = {
        "data_type": "company_announcement",
        "requested_sources": ["cninfo", "sse"], "attempted_sources": ["cninfo"],
        "selected_source": "cninfo", "fallback_used": False,
        "status": "success", "missing_fields": [], "warnings": [],
    }
    data.update(overrides)
    return data


# ---------- 正常 ----------

def test_source_valid_and_matches_schema():
    s = Source(**valid_source())
    assert validate_model(s) == []


def test_probe_valid_and_matches_schema():
    p = SourceProbe(**valid_probe())
    assert validate_model(p) == []


def test_route_valid_and_matches_schema():
    r = DataRoute(**valid_route())
    assert validate_model(r) == []


# ---------- 边界 ----------

def test_source_score_bounds_ok():
    """分数 0 和 5 为合法边界。"""
    s = Source(**valid_source(authority_score=0, accuracy_score=5))
    assert s.authority_score == 0 and s.accuracy_score == 5


def test_source_nullable_fields_ok():
    s = Source(**valid_source(rate_limit=None, last_verified_at=None))
    assert s.rate_limit is None


def test_source_user_only_access_level_matches_registry_contract():
    source = Source(**valid_source(access_level="user_only"))
    assert source.access_level == "user_only"


def test_source_local_file_reference_storage_policy_matches_registry_contract():
    source = Source(**valid_source(storage_policy="local_file_reference"))
    assert source.storage_policy == "local_file_reference"


# ---------- 失败 ----------

def test_source_score_out_of_range_fails():
    with pytest.raises(ValidationError):
        Source(**valid_source(authority_score=6))
    with pytest.raises(ValidationError):
        Source(**valid_source(accuracy_score=-1))


def test_source_invalid_enum_fails():
    with pytest.raises(ValidationError):
        Source(**valid_source(access_level="super_public"))
    with pytest.raises(ValidationError):
        Source(**valid_source(source_tier="Z"))
    with pytest.raises(ValidationError):
        Source(**valid_source(status="frozen"))


def test_probe_invalid_status_fails():
    with pytest.raises(ValidationError):
        SourceProbe(**valid_probe(status="maybe"))


def test_route_invalid_status_fails():
    with pytest.raises(ValidationError):
        DataRoute(**valid_route(status="unknown_status"))


def test_source_schema_rejects_extra_field():
    from tests.fixtures import samples

    with pytest.raises(ValidationError):
        Source(**samples.invalid_extra_field(valid_source()))


# ---------- URL 标准化 ----------

def test_normalize_url_basics():
    assert normalize_url("HTTP://Example.COM:80/a/b/") == "http://example.com/a/b"
    assert normalize_url("https://example.com:443/x?q=1#frag") == "https://example.com/x?q=1"
    assert normalize_url("https://example.com:8443/x") == "https://example.com:8443/x"


def test_normalized_url_hash_deterministic():
    assert normalized_url_hash("https://example.com/a") == \
        normalized_url_hash("https://EXAMPLE.com/a/")
    assert normalized_url_hash("https://example.com/a") != \
        normalized_url_hash("https://example.com/b")


# ---------- 限速策略 ----------

def test_rate_limit_policy_bounds():
    p = RateLimitPolicy(requests_per_minute=10, backoff_seconds=2.0, max_retries=3)
    assert p.requests_per_minute == 10
    assert p.max_retries == 3
    p2 = RateLimitPolicy()  # 默认：无限制
    assert p2.requests_per_minute == 0


# ---------- SourceRegistry ----------

@pytest.fixture()
def registry_file(tmp_path):
    import yaml

    p = tmp_path / "sources.yaml"
    payload = {"sources": {"a1": valid_source(source_id="a1", name="源A")}}
    p.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return p


def test_registry_load_and_query(registry_file):
    reg = SourceRegistry(registry_file)
    assert reg.ids() == ["a1"]
    assert reg.get("a1").name == "源A"
    assert reg.get("missing") is None
    assert reg.by_status("candidate")[0].source_id == "a1"


def test_registry_invalid_entry_raises(registry_file):
    import yaml

    payload = {"sources": {"bad": valid_source(source_id="bad", authority_score=99)}}
    registry_file.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        SourceRegistry(registry_file)


def test_registry_update_and_write_back(registry_file):
    reg = SourceRegistry(registry_file)
    reg.mark_verified("a1", status="approved", stability_score=3)
    reg2 = SourceRegistry(registry_file)  # 重新加载验证写回
    s = reg2.get("a1")
    assert s.status == "approved"
    assert s.stability_score == 3
    assert s.last_verified_at is not None


def test_registry_missing_file_is_empty(tmp_path):
    reg = SourceRegistry(tmp_path / "nope.yaml")
    assert reg.all() == []
