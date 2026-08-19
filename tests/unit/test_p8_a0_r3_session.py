from __future__ import annotations

from typing import Any

from research_os.agent_runtime import ResearchOSToolFacade


class ContinuationFixture:
    """A deterministic session contract test: every follow-up reads authority again."""

    def __init__(self) -> None:
        self.target: str | None = None
        self.readiness = "A"
        self.calls: list[str] = []
        self.facade = ResearchOSToolFacade({
            "get_company_profile": self.get_company_profile,
            "check_data_readiness": self.check_data_readiness,
        })

    def get_company_profile(self, target: str = "") -> dict[str, Any]:
        self.calls.append("get_company_profile")
        self.target = target
        return {"status": "success", "target": target}

    def check_data_readiness(self, target: str = "") -> dict[str, Any]:
        self.calls.append("check_data_readiness")
        return {"status": "success", "target": target or self.target, "marker": self.readiness}

    def turn(self, prompt: str) -> dict[str, Any]:
        if self.target is None:
            return {"status": "insufficient_evidence", "reason": "missing_session_target"}
        return self.facade.call("check_data_readiness", target=self.target)


def test_same_session_follow_up_rereads_latest_authority():
    fixture = ContinuationFixture()
    fixture.facade.call("get_company_profile", target="600519.SH")
    assert fixture.turn("数据缺口？")["marker"] == "A"
    fixture.readiness = "B"
    latest = fixture.turn("刚才这家公司的数据缺口主要是什么？")
    assert latest["marker"] == "B"
    assert fixture.calls.count("check_data_readiness") == 2


def test_new_session_follow_up_does_not_assume_previous_target():
    fixture = ContinuationFixture()
    result = fixture.turn("刚才这家公司的数据缺口主要是什么？")
    assert result["status"] == "insufficient_evidence"
    assert fixture.calls == []
