"""P7-D0 scenario requirement registry + brief watchlist tests.

覆盖：10/10 scenario coverage、No Source Leakage（registry 无 source_id/selected_source/
provider_id）、Brief A/C 存在、FAST_NEWS ∈ A 且 ∉ C、window 不重算、Loader 严格性。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_os.brief.watchlist import BriefWatchlistRegistry
from research_os.models import ScenarioDataRequirement
from research_os.routing.scenario_requirements import (
    SCENARIO_IDS,
    ScenarioDataRequirementRegistry,
)

ROOT = Path(__file__).resolve().parents[2]

REQ_PATH = ROOT / "registry" / "scenario_data_requirements.yaml"
WL_PATH = ROOT / "registry" / "brief_watchlist.yaml"

SCENARIOS_10 = {
    "morning_brief", "abnormal_move_analysis", "stock_research_report",
    "industry_research", "theme_discovery", "evening_brief", "daily_review",
    "stock_review", "earnings_expectation", "first_coverage",
}


@pytest.fixture(scope="module")
def registry() -> ScenarioDataRequirementRegistry:
    return ScenarioDataRequirementRegistry(REQ_PATH)


@pytest.fixture(scope="module")
def watchlist() -> BriefWatchlistRegistry:
    return BriefWatchlistRegistry(WL_PATH)


class TestScenarioCoverage:
    def test_all_10_scenarios_covered(self, registry):
        covered = {r.scenario for r in registry.all()}
        assert covered == SCENARIOS_10
        assert len(covered) == 10

    def test_no_11th_scenario(self, registry):
        for req in registry.all():
            assert req.scenario in SCENARIOS_10

    def test_every_scenario_has_requirements(self, registry):
        for scenario in SCENARIOS_10:
            reqs = registry.for_scenario(scenario)
            assert len(reqs) >= 1, f"{scenario} 无 requirement"


class TestNoSourceLeakage:
    def test_registry_yaml_has_no_source_keys(self):
        data = yaml.safe_load(REQ_PATH.read_text(encoding="utf-8"))
        text = REQ_PATH.read_text(encoding="utf-8")
        for forbidden in ("source_id", "selected_source", "provider_id"):
            assert forbidden not in text, f"scenario_data_requirements.yaml 出现 {forbidden}"

    def test_registry_no_unknown_scenario(self, registry):
        assert set(registry._by_scenario.keys()) == set(SCENARIO_IDS)


class TestBriefAC:
    def test_morning_a_and_c_exist(self, registry):
        purposes = {r.purpose for r in registry.for_scenario("morning_brief")}
        assert "brief_event_discovery" in purposes
        assert "brief_attention_monitoring" in purposes

    def test_evening_a_and_c_exist(self, registry):
        purposes = {r.purpose for r in registry.for_scenario("evening_brief")}
        assert "brief_event_discovery" in purposes
        assert "brief_attention_monitoring" in purposes

    def test_fast_news_only_in_a(self, registry):
        for scenario in ("morning_brief", "evening_brief"):
            for req in registry.for_scenario(scenario):
                if req.data_type == "news_flash":
                    assert req.purpose == "brief_event_discovery", \
                        f"news_flash 在 {scenario} 必须属于 A"
            # 任何 C requirement 的 data_type 都不得是 news_flash
            for req in registry.for_scenario(scenario):
                if req.purpose == "brief_attention_monitoring":
                    assert req.data_type != "news_flash"

    def test_brief_attention_scope_watchlist(self, registry):
        for scenario in ("morning_brief", "evening_brief"):
            attn = [r for r in registry.for_scenario(scenario)
                    if r.purpose == "brief_attention_monitoring"]
            assert len(attn) == 1
            assert attn[0].scope.scope_type == "watchlist"
            assert attn[0].data_type == "brief_attention_content"

    def test_brief_event_content_registered(self, registry):
        for scenario in ("morning_brief", "evening_brief"):
            ev = [r for r in registry.for_scenario(scenario)
                  if r.data_type == "brief_event_content"]
            assert len(ev) == 1
            assert ev[0].purpose == "brief_event_discovery"


class TestWindowPolicy:
    def test_brief_uses_scenario_window(self, registry):
        for scenario in ("morning_brief", "evening_brief"):
            for req in registry.for_scenario(scenario):
                assert req.time_policy == "scenario_window", \
                    f"{req.requirement_id} 必须使用 scenario_window"


class TestRegistryStrictness:
    def test_duplicate_requirement_id_rejected(self, tmp_path, registry):
        # 完整 10 场景 + morning_brief 内部重复 requirement_id
        p = tmp_path / "dup.yaml"
        lines = ["scenarios:"]
        for sc in sorted(SCENARIO_IDS):
            lines.append(f"  {sc}:\n    requirements:")
            n = 2 if sc == "morning_brief" else 1
            for i in range(n):
                req_id = "r-morning_brief" if sc == "morning_brief" else f"r-{sc}"
                lines.append(_req_yaml(sc, req_id).rstrip("\n"))
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="重复 requirement_id"):
            ScenarioDataRequirementRegistry(p)

    def test_unknown_field_rejected(self, tmp_path):
        p = tmp_path / "field.yaml"
        p.write_text("scenarios:\n  morning_brief:\n    requirements:\n"
                     "      - requirement_id: r\n        scenario: morning_brief\n"
                     "        purpose: research_input\n        data_type: d\n"
                     "        scope: {scope_type: global}\n"
                     "        time_policy: as_of_snapshot\n        required: false\n"
                     "        minimum_fields: []\n        minimum_coverage: 0.0\n"
                     "        minimum_source_tier: D\n        freshness_seconds: 0\n"
                     "        point_in_time_policy: not_applicable\n"
                     "        acceptable_fallback_modes: []\n"
                     "        degradation_policy: degraded\n        notes: ''\n"
                     "        source_id: cls\n", encoding="utf-8")
        with pytest.raises(ValueError):
            ScenarioDataRequirementRegistry(p)


class TestWatchlist:
    def test_watchlist_loads(self, watchlist):
        assert len(watchlist.all()) == 25
        assert watchlist.groups() == ["community", "financial_media", "industry_media", "institution"]

    def test_watchlist_stable_order(self, watchlist):
        entries = watchlist.all()
        keys = [(e.group, e.priority, e.watch_id) for e in entries]
        assert keys == sorted(keys)

    def test_watchlist_not_source_registry(self):
        data = yaml.safe_load(WL_PATH.read_text(encoding="utf-8"))
        for entry in data["watchlist"]:
            # watchlist 条目不携带平台级 source 能力字段
            assert "source_tier" not in entry
            assert "automation_level" not in entry


# ---------- R1: fail-closed scenario keys + watchlist content_scope / verification ----------

def _req_yaml(scenario: str, req_id: str, extra: str = "") -> str:
    return (f"      - requirement_id: {req_id}\n        scenario: {scenario}\n"
            f"        purpose: research_input\n        data_type: d\n"
            f"        scope: {{scope_type: global}}\n"
            f"        time_policy: as_of_snapshot\n        required: false\n"
            f"        minimum_fields: []\n        minimum_coverage: 0.0\n"
            f"        minimum_source_tier: D\n        freshness_seconds: 0\n"
            f"        point_in_time_policy: not_applicable\n"
            f"        acceptable_fallback_modes: []\n"
            f"        degradation_policy: degraded\n        notes: ''\n{extra}")


def _full_10_scenarios_yaml() -> str:
    lines = ["scenarios:"]
    for i, sc in enumerate(sorted(SCENARIO_IDS)):
        lines.append(f"  {sc}:\n    requirements:\n" + _req_yaml(sc, f"r-{sc}"))
    return "\n".join(lines)


class TestR1ScenarioFailClosed:
    def test_extra_11th_scenario_rejected(self, tmp_path):
        """完整合法 10 场景 + unknown_11th → ValueError / 未知 Scenario（fail-closed）。"""
        p = tmp_path / "extra.yaml"
        text = _full_10_scenarios_yaml() + "\n  unknown_11th:\n    requirements:\n" + \
               _req_yaml("unknown_11th", "r-evil")
        p.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="未知 Scenario"):
            ScenarioDataRequirementRegistry(p)

    def test_missing_scenario_rejected(self, tmp_path):
        """合法十场景中删除一个 → ValueError / 缺少 Scenario。"""
        p = tmp_path / "missing.yaml"
        drop = "morning_brief"
        lines = []
        for sc in sorted(SCENARIO_IDS):
            if sc == drop:
                continue
            lines.append(f"  {sc}:\n    requirements:\n" + _req_yaml(sc, f"r-{sc}"))
        p.write_text("scenarios:\n" + "\n".join(lines), encoding="utf-8")
        with pytest.raises(ValueError, match="缺少 Scenario"):
            ScenarioDataRequirementRegistry(p)

    def test_wrapper_unknown_field_rejected(self, tmp_path):
        """scenario wrapper 出现 source/provider/foo → 拒绝。"""
        p = tmp_path / "wrapper.yaml"
        text = _full_10_scenarios_yaml().replace(
            "  morning_brief:\n", "  morning_brief:\n    runtime_config: {x: 1}\n", 1)
        p.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="未知字段"):
            ScenarioDataRequirementRegistry(p)


class TestR1WatchlistContentScope:
    def test_cls_c_item_non_fast_news_only(self, watchlist):
        cls_entries = [e for e in watchlist.all() if "财联社" in e.name or "cls" in e.source_reference]
        assert len(cls_entries) >= 1
        for e in cls_entries:
            assert e.content_scope == "non_fast_news_only"

    def test_all_entries_have_content_scope(self, watchlist):
        for e in watchlist.all():
            assert e.content_scope in (
                "all_public_content", "non_fast_news_only", "public_institution_material"
            )

    def test_institution_entries_public_institution_material(self, watchlist):
        for e in watchlist.by_group("institution"):
            assert e.content_scope == "public_institution_material"

    def test_invalid_content_scope_rejected(self, tmp_path):
        from research_os.brief.watchlist import BriefWatchlistRegistry
        p = tmp_path / "wl.yaml"
        p.write_text("watchlist:\n"
                     "  - watch_id: w1\n    group: community\n    name: x\n"
                     "    platform: community\n    content_scope: trend_stream\n", encoding="utf-8")
        with pytest.raises(ValueError):
            BriefWatchlistRegistry(p)

    def test_fast_news_still_not_in_c(self, registry):
        for scenario in ("morning_brief", "evening_brief"):
            for req in registry.for_scenario(scenario):
                if req.purpose == "brief_attention_monitoring":
                    assert req.data_type != "news_flash"


class TestR1LastVerifiedAt:
    def test_null_is_legal(self, watchlist):
        for e in watchlist.all():
            assert e.last_verified_at is None

    def test_invalid_iso_rejected(self, tmp_path):
        from research_os.brief.watchlist import BriefWatchlistRegistry
        p = tmp_path / "wl.yaml"
        p.write_text("watchlist:\n"
                     "  - watch_id: w1\n    group: community\n    name: x\n"
                     "    platform: community\n    last_verified_at: 'yesterday'\n", encoding="utf-8")
        with pytest.raises(ValueError):
            BriefWatchlistRegistry(p)

    def test_valid_iso_accepted(self, tmp_path):
        from research_os.brief.watchlist import BriefWatchlistRegistry
        p = tmp_path / "wl.yaml"
        p.write_text("watchlist:\n"
                     "  - watch_id: w1\n    group: community\n    name: x\n"
                     "    platform: community\n"
                     "    last_verified_at: '2026-08-11T08:00:00+08:00'\n", encoding="utf-8")
        wl = BriefWatchlistRegistry(p)
        assert wl.all()[0].last_verified_at == "2026-08-11T08:00:00+08:00"
