"""三个核心研究场景的 Pipeline 适配器。"""
from research_os.orchestrator.runners.abnormal_move import AbnormalMoveScenarioRunner
from research_os.orchestrator.runners.equity_research import EquityResearchScenarioRunner
from research_os.orchestrator.runners.morning_brief import MorningBriefScenarioRunner

__all__ = ["MorningBriefScenarioRunner", "AbnormalMoveScenarioRunner", "EquityResearchScenarioRunner"]
