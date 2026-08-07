"""Phase 4.1 真实端到端验收的确定性准备与脱敏摘要。

公司、官方 URL、披露时间和人工复核 locator 全部来自版本化 YAML；运行代码不
写死验收对象。原始 PDF、生成输入和报告均位于 Git 忽略目录。
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from research_os.documents import import_disclosure
from research_os.financials.evidence_binding import CORE_FINANCIAL_CODES
from research_os.orchestrator import Orchestrator
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult
from research_os.storage import Database

FINANCIAL_COLUMNS = [
    "company_entity_id", "period_start", "period_end", "fiscal_year", "report_type",
    "statement_scope", "statement_type", "taxonomy_code", "label_raw", "value",
    "unit_scale", "currency", "published_at",
]
MANDATORY_SEMANTIC_TASKS = {
    "business_description_normalization", "management_statement_summary",
    "competitive_factor_candidates", "catalyst_candidates", "risk_candidates",
    "counter_evidence_organizing", "research_questions",
}
PROHIBITED_OUTPUT_TERMS = (
    "目标价", "买入评级", "建议买入", "建议卖出", "仓位建议", "明日交易建议",
)


@dataclass(frozen=True)
class PreparedCase:
    case: Dict[str, Any]
    request: Dict[str, Any]
    financial_file: Path | None
    binding_file: Path | None
    official_documents: List[Dict[str, Any]]


def load_phase4_acceptance_config(project_root: Path) -> Dict[str, Any]:
    path = Path(project_root) / "config" / "equity_research_acceptance.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Phase 4 验收配置缺少 cases")
    case_ids = [case.get("case_id") for case in payload["cases"]]
    if any(not case_id for case_id in case_ids) or len(case_ids) != len(set(case_ids)):
        raise ValueError("Phase 4 验收 case_id 缺失或重复")
    return payload


def _case_by_id(config: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    matches = [case for case in config["cases"] if case.get("case_id") == case_id]
    if len(matches) != 1:
        raise ValueError(f"验收案例不存在或不唯一: {case_id}")
    return matches[0]


def _write_financial_csv(path: Path, entity: str, documents: List[Dict[str, Any]]) -> None:
    rows: List[Dict[str, Any]] = []
    for document in documents:
        period_end = document["report_period_end"]
        fiscal_year = int(document["fiscal_year"])
        facts = document.get("facts") or {}
        missing = sorted(CORE_FINANCIAL_CODES - set(facts))
        if missing:
            raise ValueError(f"{entity}/{fiscal_year} 缺核心科目: {missing}")
        for code, fact in facts.items():
            rows.append({
                "company_entity_id": f"company:{entity}",
                "period_start": f"{fiscal_year}-01-01",
                "period_end": period_end,
                "fiscal_year": fiscal_year,
                "report_type": "annual",
                "statement_scope": "consolidated",
                "statement_type": fact["statement_type"],
                "taxonomy_code": code,
                "label_raw": fact["label"],
                "value": str(fact["value"]),
                "unit_scale": int(document["unit_scale"]),
                "currency": "CNY",
                "published_at": document["published_at"],
            })
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FINANCIAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _locator(
    *, document: Dict[str, Any], imported: Dict[str, Any], code: str,
    fact: Dict[str, Any], as_of: str,
) -> Dict[str, Any]:
    value = str(fact["value"])
    label = str(fact["label"])
    page = int(fact["page"])
    return {
        "taxonomy_code": code,
        "period_end": document["report_period_end"],
        "statement_scope": "consolidated",
        "document_id": imported["document_id"],
        "document_evidence_id": imported["evidence_id"],
        "locator_kind": "cell",
        "page_start": page,
        "page_end": page,
        "section_path": ["财务报表", fact["statement_type"]],
        "table_id": f"{document['key']}-{fact['statement_type']}",
        "row_index": 0,
        "column_index": 1,
        "cell_reference": f"p{page}:{code}",
        "text_start": None,
        "text_end": None,
        "structured_field": code,
        "source_excerpt": f"{label} {value}（{document['unit_scale']} 元/报表单位）",
        "reported_raw_value": value,
        "currency": "CNY",
        "unit_scale": int(document["unit_scale"]),
        "confirmation_status": "confirmed",
        "confirmed_by": "phase4.1-acceptance-review",
        "confirmed_at": as_of,
        "correction_reason": None,
    }


def prepare_phase4_case(
    project_root: Path, db: Database, *, case_id: str,
) -> PreparedCase:
    """导入官方原件并生成财务 CSV 与 locator 清单；不调用网络 Provider。"""
    root = Path(project_root)
    config = load_phase4_acceptance_config(root)
    case = _case_by_id(config, case_id)
    as_of = config["as_of"]
    workspace = root / "data" / "acceptance" / "phase4" / case_id
    workspace.mkdir(parents=True, exist_ok=True)
    documents = list(case.get("documents") or [])
    request: Dict[str, Any] = {
        "entity": case["entity"], "date": config["report_date"], "as_of": as_of,
        "depth": case.get("depth", "deep"), "periods": 2, "live": True,
        "force": True, "source_policy": "public_first",
    }
    if not documents:
        return PreparedCase(case, request, None, None, [])

    imported_documents: List[Dict[str, Any]] = []
    locators: List[Dict[str, Any]] = []
    for document in documents:
        source_file = root / document["file"]
        if not source_file.is_file():
            raise FileNotFoundError(
                f"验收原件缺失: {source_file}；先通过已验证公开来源下载")
        result = import_disclosure(
            root, db, entity_code=f"company:{case['entity']}", file_path=source_file,
            source_id=document["source_id"], source_url=document["source_url"],
            publisher=document["publisher"], published_at=document["published_at"],
            document_type="annual_report", title=document["title"],
            report_period_end=document["report_period_end"],
            fiscal_year=int(document["fiscal_year"]),
        ).model_dump()
        imported_documents.append(result)
        for code, fact in document["facts"].items():
            locators.append(_locator(
                document=document, imported=result, code=code, fact=fact, as_of=as_of))

    financial_file = workspace / "official_financial_facts.csv"
    binding_file = workspace / "financial_evidence_binding.json"
    _write_financial_csv(financial_file, case["entity"], documents)
    binding_file.write_text(json.dumps({
        "binding_version": "1.0.0",
        "company_entity_id": f"company:{case['entity']}",
        "as_of": as_of,
        "locators": locators,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    request["financial_files"] = [str(financial_file)]
    request["financial_bindings"] = [str(binding_file)]
    return PreparedCase(case, request, financial_file, binding_file, imported_documents)


def run_phase4_case(project_root: Path, *, case_id: str) -> ScenarioExecutionResult:
    """经统一 Orchestrator 运行一个显式选择的真实验收案例。"""
    root = Path(project_root)
    db = Database(root / "data" / "sqlite" / "research.db")
    db.initialize()
    try:
        prepared = prepare_phase4_case(root, db, case_id=case_id)
        orchestrator = Orchestrator(root, db=db)
        return orchestrator.execute("stock_research_report", prepared.request)
    finally:
        db.close()


def summarize_phase4_case(
    project_root: Path, result: ScenarioExecutionResult, *, expected_status: str,
) -> Dict[str, Any]:
    """只读取正式产物，形成不含 Prompt、响应全文或凭证的机器摘要。"""
    run_dir = Path(result.run_dir or "")
    if not run_dir.is_dir():
        return {
            "task_id": result.task_id, "entity": None, "report_status": result.status,
            "expected_status": expected_status, "validator_status": result.validation_status,
            "provider_live": False, "provider_id": None, "flash_calls": 0,
            "pro_calls": 0, "official_documents": 0,
            "core_financial_evidence_qualified": False,
            "mandatory_semantic_tasks": {}, "missing_core_modules": [],
            "prohibited_output_hits": [], "report_path": result.report_path,
        }

    def read_json(name: str, default: Any) -> Any:
        path = run_dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default

    request = read_json("equity_research_request.json", {})
    research = read_json("equity_research_result.json", {})
    route = read_json("model_route.json", {})
    validation = read_json("validation.json", {})
    documents = read_json("document_index.json", [])
    facts = []
    facts_path = run_dir / "financial_facts.jsonl"
    if facts_path.is_file():
        facts = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line]
    task_records = route.get("task_records") or []
    tasks = {
        record.get("task_name"): record.get("validation_status")
        for record in task_records if record.get("task_name") in MANDATORY_SEMANTIC_TASKS
    }
    report_text = ""
    final_path = run_dir / "final.md"
    if final_path.is_file():
        report_text = final_path.read_text(encoding="utf-8")
    disclaimer_marker = "本报告由 AI＋A 股投研系统自动生成"
    report_body = report_text.split(disclaimer_marker, 1)[0]
    budget = route.get("budget") or {}
    qualified_codes = {
        fact.get("taxonomy_code") for fact in facts
        if fact.get("taxonomy_code") in CORE_FINANCIAL_CODES
        and fact.get("source_document_id") and fact.get("source_block_ids")
        and fact.get("evidence_ids")
    }
    provider_ids = sorted({
        record.get("provider") for record in task_records
        if record.get("provider") and record.get("validation_status") == "pass"
    })
    return {
        "task_id": result.task_id,
        "entity": request.get("security_entity_id", "").removeprefix("security:"),
        "report_status": research.get("research_status", result.status),
        "expected_status": expected_status,
        "provider_live": bool(route.get("llm_called")),
        "provider_id": provider_ids[0] if len(provider_ids) == 1 else provider_ids,
        "flash_calls": int(budget.get("flash_used", 0)),
        "pro_calls": int(budget.get("pro_used", 0)),
        "official_documents": len(documents) if isinstance(documents, list) else 0,
        "core_financial_evidence_qualified": qualified_codes == set(CORE_FINANCIAL_CODES),
        "mandatory_semantic_tasks": tasks,
        "missing_core_modules": (research.get("coverage") or {}).get("missing_core_modules", []),
        "validator_status": validation.get("status", result.validation_status),
        "prohibited_output_hits": [term for term in PROHIBITED_OUTPUT_TERMS if term in report_body],
        "report_path": result.report_path,
    }


def write_phase4_acceptance_summary(
    project_root: Path, *, case_id: str, result: ScenarioExecutionResult,
    expected_status: str,
) -> Path:
    summary = summarize_phase4_case(project_root, result, expected_status=expected_status)
    if not summary.get("entity"):
        config = load_phase4_acceptance_config(Path(project_root))
        summary["entity"] = _case_by_id(config, case_id)["entity"]
    output = Path(project_root) / "reports" / "acceptance" / "phase4" / f"{case_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
