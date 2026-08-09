"""Phase 6A 行业研究流水线（IndustryResearchPipeline）。

5 阶段确定性流水线：
1. _build_research_context  —— GraphQueryService + KnowledgeContextBuilder
2. _produce_dimension_findings —— 21 维行业研究维度 FACT / INSUFFICIENT_EVIDENCE
3. _assess_evidence_quality —— 证据资格汇总与质量评级
4. _run_semantic_analysis —— LLM 语义分析（无 LLM 时 llm_called=False）
5. _render_report —— Markdown 报告渲染

核心约束：
- as_of 必填（禁止默认 now()），fail-closed
- 证据资格校验链：validate_evidence_ids_chain（evidence_adapter 权威入口）
- KnowledgeContext ≠ Evidence（报告必须显式标注免责声明）
- 全部 21 维产出输出（FACT / INSUFFICIENT_EVIDENCE / NON_EVIDENTIARY_CONTEXT）
- 零 LLM 确定性路径：deterministic_only=True 时完全跳过语义分析
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from research_os.knowledge.context_builder import KnowledgeContextBuilder
from research_os.knowledge.query import GraphQueryService, QueryError

logger = logging.getLogger(__name__)

# ── 21 维行业研究维度 ────────────────────────────────────────
# 每维对应一个行业分析核心问题；维度 ID 作为报告的 stable anchor。
INDUSTRY_DIMENSIONS: Tuple[Dict[str, Any], ...] = (
    # (dimension_id, chinese_label, description, graph_hint_keys)
    {"id": "industry_overview",        "label": "行业概览",
     "desc": "行业定义、边界、核心产品/服务、产业链位置总览。",
     "hint_node_types": ("Industry", "IndustrySegment"),
     "hint_relations": ("BELONGS_TO",)},
    {"id": "market_size",              "label": "市场规模",
     "desc": "行业总市场规模（TAM/SAM/SOM）、历史规模与预测。",
     "hint_node_types": ("Industry", "Metric"),
     "hint_relations": ("HAS_METRIC",)},
    {"id": "growth_rate",             "label": "增长率",
     "desc": "行业收入/产量/用户量的历史 CAGR 与未来增速预期。",
     "hint_node_types": ("Industry", "Metric"),
     "hint_relations": ("HAS_METRIC",)},
    {"id": "industry_lifecycle",      "label": "行业生命周期",
     "desc": "导入期/成长期/成熟期/衰退期判定及阶段特征。",
     "hint_node_types": ("Industry", "IndustrySegment"),
     "hint_relations": ("BELONGS_TO",)},
    {"id": "supply_chain_structure",  "label": "供应链结构",
     "desc": "上游原材料→中游制造→下游渠道/终端；关键瓶颈环节。",
     "hint_node_types": ("Industry", "Material", "Equipment", "Application"),
     "hint_relations": ("UPSTREAM_OF", "DOWNSTREAM_OF", "SUPPLIES", "PURCHASES_FROM", "PRODUCES")},
    {"id": "competitive_landscape",   "label": "竞争格局",
     "desc": "主要参与者、市场份额分布、竞争维度（品牌/成本/技术/渠道）。",
     "hint_node_types": ("Industry", "Company"),
     "hint_relations": ("BELONGS_TO", "COMPETES_WITH")},
    {"id": "market_concentration",    "label": "市场集中度",
     "desc": "CR3/CR5/HHI 等集中度指标；寡头/分散/头部集中格局。",
     "hint_node_types": ("Industry", "Company", "Metric"),
     "hint_relations": ("BELONGS_TO", "HAS_METRIC")},
    {"id": "entry_barriers",          "label": "进入壁垒",
     "desc": "资金门槛、技术壁垒、牌照/资质、品牌、规模经济、网络效应。",
     "hint_node_types": ("Industry", "Technology", "Policy"),
     "hint_relations": ("USES_TECHNOLOGY", "AFFECTS")},
    {"id": "substitute_threat",       "label": "替代威胁",
     "desc": "替代品/替代技术对行业的需求侵蚀风险。",
     "hint_node_types": ("Industry", "IndustrySegment", "Technology"),
     "hint_relations": ("SUBSTITUTES",)},
    {"id": "buyer_power",             "label": "买方议价力",
     "desc": "下游客户集中度、转换成本、价格敏感度。",
     "hint_node_types": ("Industry", "IndustrySegment", "Application"),
     "hint_relations": ("DOWNSTREAM_OF", "PURCHASES_FROM")},
    {"id": "supplier_power",          "label": "供方议价力",
     "desc": "上游供应商集中度、原材料稀缺性、切换成本。",
     "hint_node_types": ("Industry", "Material"),
     "hint_relations": ("UPSTREAM_OF", "SUPPLIES")},
    {"id": "technology_trends",       "label": "技术趋势",
     "desc": "核心技术路线、研发方向、专利格局、技术迭代速度。",
     "hint_node_types": ("Industry", "Technology"),
     "hint_relations": ("USES_TECHNOLOGY", "APPLIED_IN")},
    {"id": "regulatory_environment",  "label": "监管环境",
     "desc": "行业监管框架、合规要求、监管机构与执法力度。",
     "hint_node_types": ("Industry", "Policy"),
     "hint_relations": ("AFFECTS", "HARMED_BY")},
    {"id": "policy_support",          "label": "政策支持",
     "desc": "产业政策/补贴/税收优惠/战略规划对行业的正向驱动。",
     "hint_node_types": ("Industry", "Policy"),
     "hint_relations": ("BENEFITS_FROM", "SUPPORTED_BY")},
    {"id": "cost_structure",          "label": "成本结构",
     "desc": "固定/可变成本比例、主要成本项（原材料/人工/折旧/能源）。",
     "hint_node_types": ("Industry", "Metric"),
     "hint_relations": ("HAS_METRIC",)},
    {"id": "profitability",           "label": "盈利能力",
     "desc": "行业平均毛利率/净利率/ROIC/EBITDA 率及趋势。",
     "hint_node_types": ("Industry", "Metric"),
     "hint_relations": ("HAS_METRIC",)},
    {"id": "capital_requirements",    "label": "资本需求",
     "desc": "资本密集度、CAPEX/营收比、投产周期、融资依赖度。",
     "hint_node_types": ("Industry", "Metric"),
     "hint_relations": ("HAS_METRIC",)},
    {"id": "cyclicality",             "label": "周期性",
     "desc": "行业与经济周期的相关性、季节性、库存周期特征。",
     "hint_node_types": ("Industry", "Metric"),
     "hint_relations": ("HAS_METRIC", "AFFECTS")},
    {"id": "regional_distribution",   "label": "区域分布",
     "desc": "产能/消费的地理分布、产业集群、区域比较优势。",
     "hint_node_types": ("Industry", "IndustrySegment"),
     "hint_relations": ("BELONGS_TO",)},
    {"id": "global_linkages",         "label": "全球联动",
     "desc": "进出口依赖度、全球供应链嵌入度、汇率/地缘影响。",
     "hint_node_types": ("Industry", "IndustrySegment"),
     "hint_relations": ("DOWNSTREAM_OF", "UPSTREAM_OF", "AFFECTS")},
    {"id": "key_risks",               "label": "关键风险",
     "desc": "行业面临的重大风险因素（技术替代/政策转向/需求坍塌/供给冲击）。",
     "hint_node_types": ("Industry", "Event", "Policy"),
     "hint_relations": ("HARMED_BY", "AFFECTS", "HAS_CATALYST")},
)

# ── 报告模板常量 ──────────────────────────────────────────────
_REPORT_DISCLAIMER = (
    "> ⚠️ **KnowledgeContext ≠ Evidence**：本报告中「知识上下文」"
    "（NON-EVIDENTIARY CONTEXT）来自图谱结构提示，未经证据资格校验，"
    "不得视为事实断言。只有标注了有效 `evidence_ids` 的 FINDING 才是"
    "经过完整证据链校验的 FACT 级结论。"
)

_FINDING_TEMPLATE_FACT = """### {label}（{dim_id}）

**判定**: ✅ FACT（证据支持）

{summary}

**支持证据**:
{evidence_list}
"""

_FINDING_TEMPLATE_INSUFFICIENT = """### {label}（{dim_id}）

**判定**: ⚠️ INSUFFICIENT_EVIDENCE

**原因**: {reason}

**图谱提示（NON-EVIDENTIARY CONTEXT）**:
{graph_hints}
"""

_FINDING_TEMPLATE_MIXED = """### {label}（{dim_id}）

**判定**: 🔶 FACT（部分证据支持）

{summary}

**有效证据**:
{evidence_list}

**图谱提示（NON-EVIDENTIARY CONTEXT）**:
{graph_hints}
"""

# ── PipelineOutcome ───────────────────────────────────────────

@dataclass
class PipelineOutcome:
    """行业研究流水线产出。"""
    status: str  # success / degraded / insufficient_evidence / failed
    run_id: str
    industry_name: str = ""
    markdown: str = ""
    findings: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)
    model_route: Dict[str, Any] = field(default_factory=dict)
    data_degraded: bool = False
    dimensions_covered: List[str] = field(default_factory=list)
    dimensions_missing: List[str] = field(default_factory=list)


# ── IndustryResearchPipeline ──────────────────────────────────

class IndustryResearchPipeline:
    """行业研究流水线（Phase 6A）。

    5 阶段确定性流程，零 LLM 路径下完全确定性。
    """

    def __init__(self, root: Path, db: Any, llm_client: Any = None):
        self.root = Path(root)
        self.db = db
        self.llm_client = llm_client

    # ── 主入口 ──────────────────────────────────────────────

    def run(self, request: Dict[str, Any]) -> PipelineOutcome:
        """执行行业研究流水线。

        Args:
            request: 必须包含 'as_of' 键；可选 industry_id / industry_name /
                     depth / deterministic_only / task_id。

        Returns:
            PipelineOutcome（含 markdown 报告、findings、质量评级等）。
        """
        run_id = request.get("task_id") or str(uuid4())
        as_of = request.get("as_of")
        if not as_of:
            return PipelineOutcome(
                status="failed",
                run_id=run_id,
                warnings=["as_of 必填；行业研究必须锁定时间断面"],
                missing_data=["as_of"],
                model_route={"mode": "deterministic_fallback", "llm_called": False},
            )

        industry_id = request.get("industry_id", "unknown")
        industry_name = request.get("industry_name", industry_id)
        depth = request.get("depth", "standard")
        max_depth = {"fast": 1, "standard": 1, "deep": 2}.get(depth, 1)
        deterministic_only = request.get("deterministic_only", True)

        warnings: List[str] = []
        missing_data: List[str] = []

        # ── Stage 1: 构建研究上下文 ─────────────────────────
        try:
            context = self._build_research_context(
                industry_id=industry_id,
                as_of=as_of,
                max_depth=max_depth,
            )
        except QueryError as e:
            return PipelineOutcome(
                status="failed",
                run_id=run_id,
                industry_name=industry_name,
                warnings=[f"图谱查询失败: {e.error_code} — {e}"],
                missing_data=["knowledge_graph_unavailable"],
                model_route={"mode": "deterministic_fallback", "llm_called": False},
            )
        except Exception as e:
            logger.exception("_build_research_context failed")
            return PipelineOutcome(
                status="degraded",
                run_id=run_id,
                industry_name=industry_name,
                warnings=[f"研究上下文构建失败: {e}"],
                missing_data=["research_context_build_failed"],
                data_degraded=True,
                model_route={"mode": "deterministic_fallback", "llm_called": False},
            )

        if context is None:
            return PipelineOutcome(
                status="insufficient_evidence",
                run_id=run_id,
                industry_name=industry_name,
                warnings=[f"行业节点 {industry_id} 不存在或 as_of={as_of} 下不可见"],
                missing_data=["industry_node_not_found"],
                data_degraded=True,
                model_route={"mode": "deterministic_fallback", "llm_called": False},
            )

        # ── Stage 2: 产出全部 21 维 findings ────────────────
        dimension_findings, dim_warnings = self._produce_dimension_findings(
            context=context,
            as_of=as_of,
        )
        warnings.extend(dim_warnings)

        # ── Stage 3: 评估证据质量 ───────────────────────────
        quality_assessment = self._assess_evidence_quality(
            context=context,
            dimension_findings=dimension_findings,
            as_of=as_of,
        )

        # ── Stage 4: 语义分析（可选 LLM）───────────────────
        semantic_result, model_route = self._run_semantic_analysis(
            context=context,
            dimension_findings=dimension_findings,
            quality_assessment=quality_assessment,
            deterministic_only=deterministic_only,
        )

        # ── Stage 5: 渲染报告 ───────────────────────────────
        markdown = self._render_report(
            industry_id=industry_id,
            industry_name=industry_name,
            as_of=as_of,
            depth=depth,
            context=context,
            dimension_findings=dimension_findings,
            quality_assessment=quality_assessment,
            semantic_result=semantic_result,
            model_route=model_route,
            warnings=warnings,
        )

        # ── 汇总状态 ────────────────────────────────────────
        fact_count = sum(
            1 for f in dimension_findings
            if f.get("judgment") == "FACT"
        )
        insufficient_count = sum(
            1 for f in dimension_findings
            if f.get("judgment") == "INSUFFICIENT_EVIDENCE"
        )
        dimensions_covered = [
            f["dimension_id"] for f in dimension_findings
            if f.get("judgment") == "FACT"
        ]
        dimensions_missing = [
            f["dimension_id"] for f in dimension_findings
            if f.get("judgment") == "INSUFFICIENT_EVIDENCE"
        ]

        if fact_count == 0:
            status = "insufficient_evidence"
        elif insufficient_count > 0:
            status = "degraded"
        else:
            status = "success"

        return PipelineOutcome(
            status=status,
            run_id=run_id,
            industry_name=industry_name,
            markdown=markdown,
            findings=dimension_findings,
            warnings=warnings,
            missing_data=missing_data,
            data_degraded=(insufficient_count > 0),
            dimensions_covered=dimensions_covered,
            dimensions_missing=dimensions_missing,
            model_route=model_route,
        )

    # ── Stage 1: _build_research_context ────────────────────

    def _build_research_context(
        self,
        industry_id: str,
        as_of: str,
        max_depth: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """使用 GraphQueryService + KnowledgeContextBuilder 构建研究上下文。

        Returns:
            KnowledgeContext.to_dict() 或 None（节点不存在）。
        """
        query_svc = GraphQueryService(self.db)
        ctx_builder = KnowledgeContextBuilder(query_svc)

        try:
            knowledge_ctx = ctx_builder.build(
                root_node_id=industry_id,
                as_of=as_of,
                max_depth=max_depth,
                direction="both",
            )
        except QueryError:
            return None

        return knowledge_ctx.to_dict()

    # ── Stage 2: _produce_dimension_findings ────────────────

    def _produce_dimension_findings(
        self,
        context: Dict[str, Any],
        as_of: str,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """为全部 21 维产出 finding（FACT / INSUFFICIENT_EVIDENCE）。

        Returns:
            (dimension_findings, warnings)
        """
        findings: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for dim_def in INDUSTRY_DIMENSIONS:
            try:
                finding = self._produce_single_dimension(
                    dim_def=dim_def,
                    context=context,
                    as_of=as_of,
                )
                findings.append(finding)
            except Exception as e:
                logger.exception(
                    "dimension finding failed dim=%s", dim_def["id"])
                findings.append({
                    "dimension_id": dim_def["id"],
                    "label": dim_def["label"],
                    "judgment": "INSUFFICIENT_EVIDENCE",
                    "summary": "",
                    "evidence_ids": [],
                    "reason": f"维度处理异常: {e}",
                    "graph_hints": "",
                })
                warnings.append(f"{dim_def['label']}: 维度处理异常 — {e}")

        return findings, warnings

    def _produce_single_dimension(
        self,
        dim_def: Dict[str, Any],
        context: Dict[str, Any],
        as_of: str,
    ) -> Dict[str, Any]:
        """为单个维度产出 finding。

        流程：
        1. 从图谱上下文中收集与该维度相关的 evidence_ids
        2. 通过 _reload_and_validate_evidence 逐条重载并校验资格
        3. 若 validEvidence 非空 → FACT（附带 evidence_ids）
        4. 否则 → INSUFFICIENT_EVIDENCE（附带图谱提示）
        """
        dim_id: str = dim_def["id"]
        label: str = dim_def["label"]
        desc: str = dim_def["desc"]
        hint_node_types: Tuple[str, ...] = dim_def["hint_node_types"]
        hint_relations: Tuple[str, ...] = dim_def["hint_relations"]

        # 1. 从图谱上下文中收集相关 evidence_ids
        relevant_eids = self._collect_relevant_evidence_ids(
            context=context,
            hint_node_types=hint_node_types,
            hint_relations=hint_relations,
        )

        # 2. 构建非证据上下文（图谱结构提示）
        graph_hints = self._build_non_evidence_context(
            context=context,
            hint_node_types=hint_node_types,
            hint_relations=hint_relations,
            dim_id=dim_id,
        )

        # 3. 重载并校验证据资格
        validation_result = self._reload_and_validate_evidence(
            evidence_ids=relevant_eids,
            as_of=as_of,
        )

        valid_eids = validation_result.get("valid", [])
        invalid_eids = validation_result.get("invalid", [])
        missing_eids = validation_result.get("missing", [])
        reasons = validation_result.get("reasons", {})

        # 4. 判定
        if valid_eids:
            # 构建 FACT finding
            evidence_list_lines = [
                f"- `{eid}` ✓ 通过资格校验"
                for eid in valid_eids
            ]
            if invalid_eids:
                for eid in invalid_eids:
                    reason_str = "; ".join(reasons.get(eid, ["未知原因"]))
                    evidence_list_lines.append(
                        f"- `{eid}` ✗ 资格不通过: {reason_str}")
            if missing_eids:
                for eid in missing_eids:
                    evidence_list_lines.append(
                        f"- `{eid}` ✗ 缺失/不可用")

            summary = (
                f"{desc}\n\n"
                f"该维度在 as_of={as_of} 时间断面下，共找到 {len(valid_eids)} 条"
                f"有效证据（总候选 {len(relevant_eids)} 条）。"
            )

            return {
                "dimension_id": dim_id,
                "label": label,
                "judgment": "FACT",
                "summary": summary,
                "evidence_ids": valid_eids,
                "invalid_evidence_ids": invalid_eids + missing_eids,
                "reason": "",
                "graph_hints": graph_hints,
            }
        else:
            # INSUFFICIENT_EVIDENCE
            reason_parts = []
            if not relevant_eids:
                reason_parts.append("图谱上下文中无相关 evidence_ids")
            if missing_eids:
                reason_parts.append(
                    f"{len(missing_eids)} 条证据缺失: {', '.join(missing_eids[:5])}"
                    f"{'...' if len(missing_eids) > 5 else ''}")
            if invalid_eids:
                reason_parts.append(
                    f"{len(invalid_eids)} 条证据资格不通过")
            reason = "; ".join(reason_parts) if reason_parts else (
                "无相关证据引用；图谱中该维度仅有结构提示，"
                "无已注册的确定性证据支撑。"
            )

            return {
                "dimension_id": dim_id,
                "label": label,
                "judgment": "INSUFFICIENT_EVIDENCE",
                "summary": "",
                "evidence_ids": [],
                "invalid_evidence_ids": invalid_eids + missing_eids,
                "reason": reason,
                "graph_hints": graph_hints,
            }

    # ── 证据收集辅助 ─────────────────────────────────────────

    @staticmethod
    def _collect_relevant_evidence_ids(
        context: Dict[str, Any],
        hint_node_types: Tuple[str, ...],
        hint_relations: Tuple[str, ...],
    ) -> List[str]:
        """从图谱上下文中收集与维度相关的 evidence_ids。

        根据 hint_node_types 和 hint_relations 筛选图谱中的节点和边，
        收集它们关联的 evidence_ids。

        Args:
            context: KnowledgeContext.to_dict() 产物。
            hint_node_types: 关注的节点类型（如 Industry、Metric）。
            hint_relations: 关注的关系类型（如 HAS_METRIC、BELONGS_TO）。

        Returns:
            去重后的 evidence_id 列表（保持 stable order）。
        """
        evidence_ids: List[str] = []
        seen: set[str] = set()

        nodes: List[Dict[str, Any]] = context.get("nodes") or []
        edges: List[Dict[str, Any]] = context.get("edges") or []

        # 从匹配节点收集 evidence_ids
        for node in nodes:
            payload = node.get("payload") or {}
            node_type = payload.get("node_type") or payload.get("type") or ""
            if hint_node_types and node_type not in hint_node_types:
                continue
            for eid in payload.get("evidence_ids") or []:
                if eid not in seen:
                    seen.add(eid)
                    evidence_ids.append(eid)

        # 从匹配边收集 evidence_ids
        for edge in edges:
            payload = edge.get("payload") or {}
            relation = payload.get("relation") or ""
            if hint_relations and relation not in hint_relations:
                continue
            for eid in payload.get("evidence_ids") or []:
                if eid not in seen:
                    seen.add(eid)
                    evidence_ids.append(eid)

        return evidence_ids

    @staticmethod
    def _build_non_evidence_context(
        context: Dict[str, Any],
        hint_node_types: Tuple[str, ...],
        hint_relations: Tuple[str, ...],
        dim_id: str,
    ) -> str:
        """构建非证据上下文（图谱结构提示）。

        从图谱中提取与维度相关的节点/边结构信息，形成 NON-EVIDENTIARY CONTEXT
        章节内容。这些提示来自图谱结构本身，不代表经过校验的事实。

        Returns:
            Markdown 格式的图谱提示文本。
        """
        nodes: List[Dict[str, Any]] = context.get("nodes") or []
        edges: List[Dict[str, Any]] = context.get("edges") or []

        matching_nodes = []
        for node in nodes:
            payload = node.get("payload") or {}
            node_type = payload.get("node_type") or payload.get("type") or ""
            if hint_node_types and node_type not in hint_node_types:
                continue
            node_id = payload.get("node_id") or node.get("node_id") or "?"
            name = payload.get("name") or payload.get("label") or node_id
            matching_nodes.append(
                f"- **{node_type}** `{node_id}`: {name} "
                f"(depth={node.get('depth', '?')}, "
                f"active={node.get('is_active', '?')})"
            )

        matching_edges = []
        for edge in edges:
            payload = edge.get("payload") or {}
            relation = payload.get("relation") or ""
            if hint_relations and relation not in hint_relations:
                continue
            src = payload.get("source_node_id") or "?"
            tgt = payload.get("target_node_id") or "?"
            matching_edges.append(
                f"- `{src}` --[{relation}]--> `{tgt}` "
                f"(assertion={payload.get('assertion_type', '?')})"
            )

        lines: List[str] = []
        if matching_nodes:
            lines.append("**相关节点**:")
            lines.extend(matching_nodes[:20])
            if len(matching_nodes) > 20:
                lines.append(f"  ... (+{len(matching_nodes) - 20} more)")
        if matching_edges:
            if lines:
                lines.append("")
            lines.append("**相关关系**:")
            lines.extend(matching_edges[:20])
            if len(matching_edges) > 20:
                lines.append(f"  ... (+{len(matching_edges) - 20} more)")

        if not lines:
            return "_该维度在图谱中无匹配的节点或边。_"

        return "\n".join(lines)

    # ── 证据重载与校验 ───────────────────────────────────────

    def _reload_and_validate_evidence(
        self,
        evidence_ids: List[str],
        as_of: str,
    ) -> Dict[str, Any]:
        """通过 evidence_adapter 重载并校验 evidence_ids 资格。

        使用 validate_evidence_ids_chain 作为唯一权威入口。
        fail-closed：任何加载/校验异常均将对应 evidence_id 归入 missing。

        Returns:
            {
                "valid": [...],
                "invalid": [...],
                "missing": [...],
                "reasons": {eid: [reason_str, ...], ...},
            }
        """
        if not evidence_ids:
            return {"valid": [], "invalid": [], "missing": [], "reasons": {}}

        from research_os.industry_research.evidence_adapter import (
            validate_evidence_ids_chain,
        )

        try:
            return validate_evidence_ids_chain(
                evidence_ids=evidence_ids,
                db=self.db,
                as_of=as_of,
            )
        except Exception as e:
            logger.exception("validate_evidence_ids_chain failed")
            return {
                "valid": [],
                "invalid": [],
                "missing": list(evidence_ids),
                "reasons": {
                    eid: [f"证据资格校验链异常: {e}"]
                    for eid in evidence_ids
                },
            }

    # ── Stage 3: _assess_evidence_quality ────────────────────

    def _assess_evidence_quality(
        self,
        context: Dict[str, Any],
        dimension_findings: List[Dict[str, Any]],
        as_of: str,
    ) -> Dict[str, Any]:
        """评估整体证据质量。

        汇总全部维度的证据资格状态，计算：
        - total_evidence_candidates: 图谱中全部候选 evidence_ids 总数
        - valid_evidence_count: 通过资格校验的证据数
        - fact_dimension_count: FACT 判定维度数
        - insufficient_dimension_count: INSUFFICIENT_EVIDENCE 维度数
        - overall_quality: "good" / "partial" / "poor"
        - source_tier_distribution: 有效证据的 source_tier 分布

        Returns:
            证据质量评估 dict。
        """
        all_eids_context: set[str] = set(context.get("evidence_ids") or [])
        valid_eids_all: set[str] = set()
        invalid_eids_all: List[str] = []
        missing_eids_all: List[str] = []

        for finding in dimension_findings:
            for eid in finding.get("evidence_ids") or []:
                valid_eids_all.add(eid)
            for eid in finding.get("invalid_evidence_ids") or []:
                if eid not in invalid_eids_all:
                    invalid_eids_all.append(eid)

        # 尝试获取有效证据的 source_tier 分布
        source_tier_dist: Dict[str, int] = {}
        evidence_summaries: List[Dict[str, Any]] = context.get("evidence") or []
        evidence_by_id: Dict[str, Dict[str, Any]] = {
            s["evidence_id"]: s for s in evidence_summaries
        }
        for eid in valid_eids_all:
            ev = evidence_by_id.get(eid)
            if ev:
                tier = ev.get("source_tier", "unknown")
                source_tier_dist[tier] = source_tier_dist.get(tier, 0) + 1

        fact_count = sum(
            1 for f in dimension_findings
            if f.get("judgment") == "FACT"
        )
        insufficient_count = len(dimension_findings) - fact_count

        if fact_count >= 15 and len(valid_eids_all) >= 10:
            overall_quality = "good"
        elif fact_count >= 5:
            overall_quality = "partial"
        else:
            overall_quality = "poor"

        # 检查图谱局限
        limitations: List[Dict[str, str]] = context.get("limitations") or []
        epistemic: Dict[str, List[str]] = context.get("epistemic") or {}

        return {
            "as_of": as_of,
            "total_evidence_candidates": len(all_eids_context),
            "valid_evidence_count": len(valid_eids_all),
            "fact_dimension_count": fact_count,
            "insufficient_dimension_count": insufficient_count,
            "overall_quality": overall_quality,
            "source_tier_distribution": source_tier_dist,
            "graph_limitations": limitations,
            "epistemic_partition": {
                "governance_count": len(epistemic.get("governance") or []),
                "facts_count": len(epistemic.get("facts") or []),
                "model_inferences_count": len(epistemic.get("model_inferences") or []),
            },
        }

    # ── Stage 4: _run_semantic_analysis ──────────────────────

    def _run_semantic_analysis(
        self,
        context: Dict[str, Any],
        dimension_findings: List[Dict[str, Any]],
        quality_assessment: Dict[str, Any],
        deterministic_only: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """运行语义分析（可选 LLM）。

        当 deterministic_only=True 或无可用 LLM 时，llm_called=False，
        语义分析返回空结果。

        Returns:
            (semantic_result, model_route)
        """
        model_route: Dict[str, Any] = {
            "mode": "deterministic_fallback",
            "llm_called": False,
        }

        if deterministic_only:
            return {
                "status": "skipped",
                "reason": "deterministic_only=True；跳过 LLM 语义分析",
                "insights": [],
            }, model_route

        # 尝试 LLM（如果配置了 Provider）
        if self.llm_client is not None and getattr(
            self.llm_client, "configured", False
        ):
            try:
                insights = self._invoke_llm_semantic_analysis(
                    context=context,
                    dimension_findings=dimension_findings,
                    quality_assessment=quality_assessment,
                )
                model_route = {
                    "mode": "llm_assisted",
                    "llm_called": True,
                    "provider": getattr(self.llm_client, "provider_name", "unknown"),
                }
                return {
                    "status": "completed",
                    "insights": insights,
                }, model_route
            except Exception as e:
                logger.warning("LLM 语义分析失败，回退确定性路径: %s", e)
                model_route = {
                    "mode": "deterministic_fallback",
                    "llm_called": False,
                    "limitation": f"LLM 调用失败: {e}",
                }
                return {
                    "status": "fallback",
                    "reason": str(e),
                    "insights": [],
                }, model_route

        # 无 LLM Client
        return {
            "status": "skipped",
            "reason": "未配置 LLM Provider；仅执行确定性分析",
            "insights": [],
        }, model_route

    def _invoke_llm_semantic_analysis(
        self,
        context: Dict[str, Any],
        dimension_findings: List[Dict[str, Any]],
        quality_assessment: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """调用 LLM 进行语义分析（占位实现）。

        实际 LLM 调用留待 Provider 集成后实现。
        当前返回空列表（确定性降级）。
        """
        # TODO: 实现 LLM 语义分析调用
        return []

    # ── Stage 5: _render_report ──────────────────────────────

    def _render_report(
        self,
        industry_id: str,
        industry_name: str,
        as_of: str,
        depth: str,
        context: Dict[str, Any],
        dimension_findings: List[Dict[str, Any]],
        quality_assessment: Dict[str, Any],
        semantic_result: Dict[str, Any],
        model_route: Dict[str, Any],
        warnings: List[str],
    ) -> str:
        """渲染 Markdown 行业研究报告。

        报告结构：
        1. 标题与元信息
        2. 免责声明（KnowledgeContext ≠ Evidence）
        3. 证据质量总览
        4. 21 维 findings（按 judgment 分组）
        5. 图谱局限与知情缺口
        6. 语义分析（如有）
        7. 警告与备注
        """
        lines: List[str] = []

        # ── 标题 ──────────────────────────────────────────
        lines.append(f"# 行业研究报告：{industry_name}")
        lines.append("")
        lines.append(f"- **行业 ID**: `{industry_id}`")
        lines.append(f"- **时间断面（as_of）**: `{as_of}`")
        lines.append(f"- **研究深度**: `{depth}`")
        lines.append(f"- **模型路由**: {model_route.get('mode', 'unknown')}")
        lines.append(f"- **LLM 已调用**: {'是' if model_route.get('llm_called') else '否'}")
        lines.append("")

        # ── 免责声明 ──────────────────────────────────────
        lines.append(_REPORT_DISCLAIMER)
        lines.append("")

        # ── 证据质量总览 ──────────────────────────────────
        lines.append("## 证据质量总览")
        lines.append("")
        lines.append(f"- **整体质量**: {quality_assessment.get('overall_quality', 'unknown')}")
        lines.append(f"- **候选证据总数（图谱）**: {quality_assessment.get('total_evidence_candidates', 0)}")
        lines.append(f"- **有效证据数（通过资格校验）**: {quality_assessment.get('valid_evidence_count', 0)}")
        lines.append(f"- **FACT 维度数**: {quality_assessment.get('fact_dimension_count', 0)}/21")
        lines.append(f"- **证据不足维度数**: {quality_assessment.get('insufficient_dimension_count', 0)}/21")
        lines.append("")

        # source_tier 分布
        tier_dist = quality_assessment.get("source_tier_distribution") or {}
        if tier_dist:
            lines.append("**有效证据来源层级分布**:")
            lines.append("")
            for tier in ("S", "A", "B", "C", "D"):
                count = tier_dist.get(tier, 0)
                if count:
                    tier_label = {
                        "S": "官方一手数据",
                        "A": "权威机构报告",
                        "B": "可靠来源",
                        "C": "一般来源",
                        "D": "低可信度来源",
                    }.get(tier, tier)
                    lines.append(f"- **Tier {tier}**（{tier_label}）: {count} 条")
            lines.append("")

        # 知情分区
        epistemic = quality_assessment.get("epistemic_partition") or {}
        lines.append("**图谱知情分区**:")
        lines.append("")
        lines.append(f"- GOVERNANCE 边: {epistemic.get('governance_count', 0)}")
        lines.append(f"- FACT 边: {epistemic.get('facts_count', 0)}")
        lines.append(f"- MODEL_INFERENCE 边: {epistemic.get('model_inferences_count', 0)}")
        lines.append("")

        # ── 21 维 Findings ────────────────────────────────
        lines.append("## 行业研究维度 Findings")
        lines.append("")

        # 分组：先 FACT，再 INSUFFICIENT_EVIDENCE
        fact_findings = [
            f for f in dimension_findings
            if f.get("judgment") == "FACT"
        ]
        insufficient_findings = [
            f for f in dimension_findings
            if f.get("judgment") == "INSUFFICIENT_EVIDENCE"
        ]

        if fact_findings:
            lines.append("### ✅ FACT（证据支持）")
            lines.append("")
            for finding in fact_findings:
                lines.append(
                    self._render_single_finding(finding)
                )

        if insufficient_findings:
            lines.append("### ⚠️ INSUFFICIENT_EVIDENCE（证据不足）")
            lines.append("")
            for finding in insufficient_findings:
                lines.append(
                    self._render_single_finding(finding)
                )

        # ── 图谱局限 ──────────────────────────────────────
        limitations: List[Dict[str, str]] = (
            context.get("limitations") or []
        )
        if limitations:
            lines.append("## 图谱局限与知情缺口")
            lines.append("")
            for lim in limitations:
                code = lim.get("code", "?")
                message = lim.get("message", "")
                lines.append(f"- **{code}**: {message}")
            lines.append("")

        # ── 语义分析 ──────────────────────────────────────
        sem_status = semantic_result.get("status", "unknown")
        if sem_status == "completed":
            lines.append("## 语义分析（LLM 辅助）")
            lines.append("")
            insights = semantic_result.get("insights") or []
            for ins in insights:
                if isinstance(ins, dict):
                    lines.append(f"- **{ins.get('topic', '')}**: {ins.get('content', '')}")
                else:
                    lines.append(f"- {ins}")
            lines.append("")
        elif sem_status in ("skipped", "fallback"):
            lines.append("## 语义分析")
            lines.append("")
            lines.append(f"> ℹ️ 语义分析未执行：{semantic_result.get('reason', '确定性路径')}")
            lines.append("")

        # ── 警告 ──────────────────────────────────────────
        if warnings:
            lines.append("## 警告与备注")
            lines.append("")
            for w in warnings:
                lines.append(f"- ⚠️ {w}")
            lines.append("")

        # ── 脚注 ──────────────────────────────────────────
        lines.append("---")
        lines.append("")
        lines.append(
            "*本报告由 IndustryResearchPipeline（Phase 6A）确定性生成。"
            "「NON-EVIDENTIARY CONTEXT」内容来自知识图谱结构提示，"
            "不作为投资决策依据。*"
        )

        return "\n".join(lines)

    @staticmethod
    def _render_single_finding(finding: Dict[str, Any]) -> str:
        """渲染单个维度 finding 为 Markdown 段落。

        Args:
            finding: _produce_single_dimension 产出。

        Returns:
            Markdown 文本。
        """
        dim_id = finding.get("dimension_id", "?")
        label = finding.get("label", dim_id)
        judgment = finding.get("judgment", "?")
        summary = finding.get("summary", "")
        evidence_ids: List[str] = finding.get("evidence_ids") or []
        reason = finding.get("reason", "")
        graph_hints = finding.get("graph_hints", "")

        if judgment == "FACT":
            evidence_list_lines = [
                f"- `{eid}`"
                for eid in evidence_ids[:10]
            ]
            if len(evidence_ids) > 10:
                evidence_list_lines.append(
                    f"  ... (+{len(evidence_ids) - 10} more)")
            evidence_list = "\n".join(evidence_list_lines) if evidence_list_lines else (
                "- _无具体 evidence_id_"
            )

            return _FINDING_TEMPLATE_FACT.format(
                label=label,
                dim_id=dim_id,
                summary=summary,
                evidence_list=evidence_list,
            )

        elif judgment == "INSUFFICIENT_EVIDENCE":
            return _FINDING_TEMPLATE_INSUFFICIENT.format(
                label=label,
                dim_id=dim_id,
                reason=reason,
                graph_hints=graph_hints or "_无图谱提示_",
            )

        else:
            # 混合或其他
            evidence_list_lines = [
                f"- `{eid}`"
                for eid in evidence_ids[:10]
            ]
            if len(evidence_ids) > 10:
                evidence_list_lines.append(
                    f"  ... (+{len(evidence_ids) - 10} more)")
            evidence_list = "\n".join(evidence_list_lines) or "- _无_"

            return _FINDING_TEMPLATE_MIXED.format(
                label=label,
                dim_id=dim_id,
                summary=summary or "部分证据支持，部分仅图谱提示。",
                evidence_list=evidence_list,
                graph_hints=graph_hints or "_无_",
            )
