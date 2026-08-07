"""Schema 校验器：所有核心对象必须通过对应 JSON Schema 校验（工程指南约束）。

确定性逻辑（Schema 校验）必须使用代码，不得交给 LLM（指南 6.3）。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import jsonschema
from jsonschema import FormatChecker, validators

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


def validate_instance(instance: Any, schema_name: str) -> List[str]:
    """校验对象是否符合对应 Schema。

    返回错误列表；空列表表示通过。校验失败不抛异常（调用方决定如何处理），
    但任何失败必须被显式处理，禁止静默失败。
    """
    schema = load_schema(schema_name)
    # 构建本地 schema registry 以支持跨文件 $ref（如 GraphChange → GraphNode / GraphEdge）
    store = {}
    for name in SCHEMA_NAMES:
        try:
            store[load_schema(name).get("$id", f"{name}.schema.json")] = load_schema(name)
        except Exception:
            pass
    # 按文件名寻址的别名（jsonschema 解析 $ref 时的默认 base URI）
    for name in SCHEMA_NAMES:
        fn = f"{name}.schema.json"
        if fn not in store:
            try:
                store[fn] = load_schema(name)
            except Exception:
                pass
    resolver = jsonschema.RefResolver.from_schema(schema, store=store)
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    # 构造 validator（禁用元 schema 校验以避免 draft-07 meta-schema 歧义）
    validator = validator_cls(schema, format_checker=_format_checker, resolver=resolver)
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
        # Phase 3：异动分析
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
        # Phase 4：个股研报
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
