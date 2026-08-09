"""Schema 校验器：所有核心对象必须通过对应 JSON Schema 校验（工程指南约束）。

确定性逻辑（Schema 校验）必须使用代码，不得交给 LLM（指南 6.3）。

M1-R2: 使用 referencing.Registry 建立本地 $ref 解析，fail-closed，无网络访问。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import jsonschema
from jsonschema import Draft7Validator, FormatChecker, validators
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from research_os.utils.time import validate_iso

# 项目根目录：优先环境变量 RESEARCH_PROJECT_PATH（wheel 安装时定位 schemas/），
# 否则按源码布局 src/research_os/validators/ -> 项目根。动态读取，CLI 会自动设置。
def get_project_root() -> Path:
    env_root = os.environ.get("RESEARCH_PROJECT_PATH")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[3]


def schema_dir() -> Path:
    return get_project_root() / "schemas"

SCHEMA_NAMES = [
    "task",
    "entity",
    "raw_item",
    "event",
    "opinion",
    "claim",
    "evidence",
    "module_result",
    "graph_change",
    # Phase 1：来源层
    "source",
    "source_probe",
    "data_route",
    "manual_inbox",
    # Phase 1.1：行情契约
    "market_realtime_snapshot",
    "market_daily_ohlcv",
    # Phase 2：晨报流水线
    "candidate_item",
    "event_cluster",
    "information_score",
    "morning_brief_run",
    # Phase 3：异动分析
    "market_daily_series_manifest",
    "market_minute_bar",
    "abnormal_move_request",
    "anomaly_metric",
    "abnormal_move_observation",
    "benchmark_candidate",
    "benchmark_selection",
    "cause_candidate",
    "cause_evidence_link",
    "attribution_result",
    "abnormal_move_run",
    # Phase 4：个股研报
    "company_profile",
    "security_profile",
    "document_record",
    "document_block",
    "financial_data_manifest",
    "financial_evidence_binding_manifest",
    "financial_report",
    "financial_fact",
    "financial_metric",
    "business_segment",
    "peer_candidate",
    "peer_selection",
    "valuation_snapshot",
    "forecast_scenario",
    "competitive_factor",
    "catalyst",
    "risk_factor",
    "research_finding",
    "equity_research_request",
    "equity_research_run",
    "equity_research_result",
    # Phase 5：产业图谱
    "graph_node",
    "graph_edge",
    "graph_change_proposal",
    "graph_review",
    # Phase 6A：行业研究与主题发现（6A-owned Schemas）
    "industry_research_request",
    "industry_research_run",
    "theme_discovery_request",
    "theme_discovery_run",
    # Phase 6B：周期复盘（6B-owned Schemas）
    "evening_brief_request",
    "evening_brief_run",
    "daily_review_request",
    "daily_review_run",
    "stock_review_request",
    "stock_review_run",
]

# 自定义格式校验：统一使用项目的 Asia/Shanghai ISO 时间口径
_format_checker = FormatChecker()
_format_checker.checkers = {
    k: v for k, v in FormatChecker().checkers.items() if k in ("uri", "date")
}


@_format_checker.checks("date-time")
def _check_datetime(value: str) -> bool:
    return isinstance(value, str) and validate_iso(value)


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    """加载 schema 文件。name 不带 .schema.json 后缀。"""
    if name not in SCHEMA_NAMES:
        raise ValueError(f"未知 Schema: {name!r}，可用: {SCHEMA_NAMES}")
    path = schema_dir() / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema 文件不存在: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def schema_path(name: str) -> Path:
    return schema_dir() / f"{name}.schema.json"


# ---- 本地 $ref Registry（M1-R2, referencing.Registry, fail-closed） ----

@lru_cache(maxsize=1)
def _build_local_registry() -> Registry:
    """构建包含全部本地 schema 的 referencing.Registry。

    $id → Resource，仅本地文件。缺失或解析失败显式报错。
    无 HTTP/HTTPS/network fallback。
    """
    resources = []
    for name in SCHEMA_NAMES:
        schema = load_schema(name)
        schema_id = schema.get("$id", f"{name}.schema.json")
        resource = Resource.from_contents(schema, default_specification=DRAFT7)
        resources.append((schema_id, resource))
    return Registry().with_resources(resources)


def validate_instance(instance: Any, schema_name: str) -> List[str]:
    """校验对象是否符合对应 Schema。

    返回错误列表；空列表表示通过。校验失败不抛异常（调用方决定如何处理），
    但任何失败必须被显式处理，禁止静默失败。
    """
    schema = load_schema(schema_name)
    registry = _build_local_registry()
    # 先用 check_schema 验证 schema 自身合法性
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    # 使用 registry 构造 validator，支持 $ref 本地解析
    Validator = validators.create(
        meta_schema=Draft7Validator.META_SCHEMA,
        validators=Draft7Validator.VALIDATORS,
        version="draft7",
        format_checker=_format_checker,
    )
    # 把 registry 传给 validator（Python 构造函数）
    validator = Validator(schema, registry=registry, format_checker=_format_checker)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    return [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


def validate_model(model: Any) -> List[str]:
    """校验 Pydantic 模型实例：dump 为 dict 后按模型名映射到 Schema。"""
    name = type(model).__name__
    schema_name = {
        "Task": "task",
        "Entity": "entity",
        "RawItem": "raw_item",
        "Event": "event",
        "Opinion": "opinion",
        "Claim": "claim",
        "Evidence": "evidence",
        "ModuleResult": "module_result",
        "GraphChange": "graph_change",
        "Source": "source",
        "SourceProbe": "source_probe",
        "DataRoute": "data_route",
        "ManualInbox": "manual_inbox",
        "MarketRealtimeSnapshot": "market_realtime_snapshot",
        "MarketDailyOhlcv": "market_daily_ohlcv",
        "CandidateItem": "candidate_item",
        "EventCluster": "event_cluster",
        "InformationScore": "information_score",
        "MorningBriefRun": "morning_brief_run",
        "MarketDailySeriesManifest": "market_daily_series_manifest",
        "MarketMinuteBar": "market_minute_bar",
        "AbnormalMoveRequest": "abnormal_move_request",
        "AnomalyMetric": "anomaly_metric",
        "AbnormalMoveObservation": "abnormal_move_observation",
        "BenchmarkCandidate": "benchmark_candidate",
        "BenchmarkSelection": "benchmark_selection",
        "CauseCandidate": "cause_candidate",
        "CauseEvidenceLink": "cause_evidence_link",
        "AttributionResult": "attribution_result",
        "AbnormalMoveRun": "abnormal_move_run",
        "CompanyProfile": "company_profile",
        "SecurityProfile": "security_profile",
        "DocumentRecord": "document_record",
        "DocumentBlock": "document_block",
        "FinancialDataManifest": "financial_data_manifest",
        "FinancialEvidenceBindingManifest": "financial_evidence_binding_manifest",
        "FinancialReport": "financial_report",
        "FinancialFact": "financial_fact",
        "FinancialMetric": "financial_metric",
        "BusinessSegment": "business_segment",
        "PeerCandidate": "peer_candidate",
        "PeerSelection": "peer_selection",
        "ValuationSnapshot": "valuation_snapshot",
        "ForecastScenario": "forecast_scenario",
        "CompetitiveFactor": "competitive_factor",
        "Catalyst": "catalyst",
        "RiskFactor": "risk_factor",
        "ResearchFinding": "research_finding",
        "EquityResearchRequest": "equity_research_request",
        "EquityResearchRun": "equity_research_run",
        "EquityResearchResult": "equity_research_result",
        # Phase 5
        "GraphNode": "graph_node",
        "GraphEdge": "graph_edge",
        "GraphChangeProposal": "graph_change_proposal",
        "GraphReview": "graph_review",
        # Phase 6A
        "IndustryResearchRequest": "industry_research_request",
        "IndustryResearchRun": "industry_research_run",
        "ThemeDiscoveryRequest": "theme_discovery_request",
        "ThemeDiscoveryRun": "theme_discovery_run",
        # Phase 6B
        "EveningBriefRequest": "evening_brief_request",
        "EveningBriefRun": "evening_brief_run",
        "DailyReviewRequest": "daily_review_request",
        "DailyReviewRun": "daily_review_run",
        "StockReviewRequest": "stock_review_request",
        "StockReviewRun": "stock_review_run",
    }.get(name)
    if schema_name is None:
        raise ValueError(f"未知模型: {name}")
    return validate_instance(model.model_dump(), schema_name)


def validate_all_schemas() -> Dict[str, List[str]]:
    """校验所有 schema 文件本身是合法 JSON Schema。

    返回 {schema_name: 错误列表}；空字典表示全部通过。
    """
    result: Dict[str, List[str]] = {}
    for name in SCHEMA_NAMES:
        try:
            schema = load_schema(name)
            validators.validator_for(schema).check_schema(schema)
            result[name] = []
        except Exception as exc:  # noqa: BLE001 —— 收集错误而非中断
            result[name] = [str(exc)]
    return result
