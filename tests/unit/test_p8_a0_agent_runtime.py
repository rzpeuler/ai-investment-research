import json
from pathlib import Path

import pytest

from research_os.agent_runtime import DurableSession, HarnessBoundary, ResearchAgentProfile, ResearchOSToolFacade, SkillRegistry


def test_profile_is_fail_closed():
    assert ResearchAgentProfile().as_dict() == {
        "name": "research-agent", "bash": False, "filesystem_write": False,
        "direct_network": False, "graph_write": False, "research_tools": True,
    }


def test_facade_exposes_structured_read_capabilities_only():
    facade = ResearchOSToolFacade({"get_company_profile": lambda **_: {"status": "success", "company": "贵州茅台"}})
    assert facade.call("get_company_profile")["status"] == "success"
    with pytest.raises(PermissionError):
        facade.call("graph_write")
    with pytest.raises(ValueError):
        ResearchOSToolFacade({"cninfo_fetch": lambda: {}})


def test_session_persists_context_and_bounds_turns(tmp_path: Path):
    session = DurableSession("demo", tmp_path, max_turns=2)
    session.add_turn("研究贵州茅台", "已识别目标", ["entity:600519.SH"])
    session.add_turn("分析现金流", "将通过正式场景分析")
    session.add_turn("继续", "保持上下文")
    session.save()
    loaded = DurableSession.load("demo", tmp_path, max_turns=2)
    assert len(loaded.messages) == 2
    assert loaded.references == ["entity:600519.SH"]
    assert json.loads(loaded.path.read_text(encoding="utf-8"))["session_id"] == "demo"
    with pytest.raises(ValueError):
        loaded.add_turn("api_key=secret", "不保存")


def test_skills_discover_and_load():
    registry = SkillRegistry(Path("agent_runtime_skills"))
    assert registry.discover() == ["financial-analysis", "industry-graph-research", "stock-research"]
    assert registry.load("stock-research").kind == "scenario"


def test_boundary_selects_tools_without_source_bypass():
    facade = ResearchOSToolFacade({"query_industry_graph": lambda **_: {"status": "success"}})
    boundary = HarnessBoundary(facade, ResearchAgentProfile())
    result = boundary.handle("产业链上有什么风险？")
    assert result["selected_tool"] == "query_industry_graph"
    assert result["result"]["status"] == "success"
