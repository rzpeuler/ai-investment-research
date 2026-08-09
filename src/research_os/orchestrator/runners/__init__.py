"""统一导出并集中定义默认研究场景 Runner。"""
from research_os.orchestrator.runners.abnormal_move import AbnormalMoveScenarioRunner
from research_os.orchestrator.runners.daily_review import DailyReviewScenarioRunner
from research_os.orchestrator.runners.earnings_expectation import (
    EarningsExpectationScenarioRunner,
)
from research_os.orchestrator.runners.equity_research import EquityResearchScenarioRunner
from research_os.orchestrator.runners.evening_brief import EveningBriefScenarioRunner
from research_os.orchestrator.runners.first_coverage import FirstCoverageScenarioRunner
from research_os.orchestrator.runners.industry_research import IndustryResearchScenarioRunner
from research_os.orchestrator.runners.morning_brief import MorningBriefScenarioRunner
from research_os.orchestrator.runners.stock_review import StockReviewScenarioRunner
from research_os.orchestrator.runners.theme_discovery import ThemeDiscoveryScenarioRunner


DEFAULT_RUNNER_TYPES = (
    MorningBriefScenarioRunner,
    AbnormalMoveScenarioRunner,
    EquityResearchScenarioRunner,
    EveningBriefScenarioRunner,
    DailyReviewScenarioRunner,
    StockReviewScenarioRunner,
    IndustryResearchScenarioRunner,
    ThemeDiscoveryScenarioRunner,
    EarningsExpectationScenarioRunner,
    FirstCoverageScenarioRunner,
)

DEFAULT_SCENARIOS = tuple(runner_type.scenario for runner_type in DEFAULT_RUNNER_TYPES)

__all__ = [
    "MorningBriefScenarioRunner",
    "AbnormalMoveScenarioRunner",
    "EquityResearchScenarioRunner",
    "EveningBriefScenarioRunner",
    "DailyReviewScenarioRunner",
    "StockReviewScenarioRunner",
    "IndustryResearchScenarioRunner",
    "ThemeDiscoveryScenarioRunner",
    "EarningsExpectationScenarioRunner",
    "FirstCoverageScenarioRunner",
    "DEFAULT_RUNNER_TYPES",
    "DEFAULT_SCENARIOS",
]
