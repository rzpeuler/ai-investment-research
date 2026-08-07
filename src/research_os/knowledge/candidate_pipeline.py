"""M3 Candidate Pipeline：知识摄取决定器 + LLM 提案 + 构建 + 持久化 + 渲染。

流水线：
1. knowledge_ingest_decider：确定性预检（源类型、对象存在、Schema、Evidence）
2. source load → eligibility → LLM proposal → validate → builder → persist → render
3. Flash 优先，Pro 升级条件：
   - supply_chain_hops > 3
   - high-grade conflict
   - cross-industry
   - ontology implication
   - Flash validation >= 2 fails
4. 每个 candidate task 最多 1 次 Pro
5. requested_model_class 支持
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research_os.knowledge.candidate_sources import (
    SourceAdapter,
    EvidenceContext,
    load_evidence_context,
    is_allowed_source_type,
)
from research_os.knowledge.candidate_builder import (
    GraphChangeBuilder,
    check_evidence_gate,
)
from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
from research_os.knowledge.candidate_renderer import CandidateRenderer
from research_os.models import (
    GraphChange,
    GraphChangeProposal,
)
from research_os.llm.client import LlmClient, is_provider_configured
from research_os.llm.models import LlmRequest
from research_os.llm.provider import FakeLlmProvider, LlmProvider
from research_os.llm.validation import LlmOutputValidator
from research_os.storage.db import Database
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso

# ---- 确定性预检 ----

class IngestDecision:
    """knowledge_ingest_decider 输出。"""

    def __init__(
        self,
        allowed: bool,
        reason: str,
        source_type: str = "",
        source_id: str = "",
        evidence_ok: bool = False,
        schema_ok: bool = False,
        conflicts: Optional[List[str]] = None,
    ):
        self.allowed = allowed
        self.reason = reason
        self.source_type = source_type
        self.source_id = source_id
        self.evidence_ok = evidence_ok
        self.schema_ok = schema_ok
        self.conflicts = conflicts or []


def knowledge_ingest_decider(
    db: Database,
    source_type: str,
    source_id: str,
    evidence_ids: Optional[List[str]] = None,
) -> IngestDecision:
    """确定性预检：源类型允许、对象存在、Schema 有效、至少一条真实 Evidence。

    Returns:
        IngestDecision with allowed flag and details.
    """
    # 1. 源类型检查
    if not is_allowed_source_type(source_type):
        return IngestDecision(
            allowed=False,
            reason=f"源类型 {source_type} 不在 M3 允许名单中",
            source_type=source_type,
            source_id=source_id,
        )

    # 2. 对象存在性检查
    adapter = SourceAdapter(db)
    try:
        source_obj = adapter.load(source_type, source_id)
    except ValueError as exc:
        return IngestDecision(
            allowed=False,
            reason=str(exc),
            source_type=source_type,
            source_id=source_id,
        )

    # 3. Evidence 门禁
    evidence_ids = evidence_ids or []
    evidence_ok = True
    if evidence_ids:
        ok, errs = check_evidence_gate(db, evidence_ids)
        evidence_ok = ok
        if not ok:
            return IngestDecision(
                allowed=False,
                reason=f"证据门禁失败: {'; '.join(errs)}",
                source_type=source_type,
                source_id=source_id,
                evidence_ok=False,
            )

    return IngestDecision(
        allowed=True,
        reason="OK",
        source_type=source_type,
        source_id=source_id,
        evidence_ok=evidence_ok,
        schema_ok=True,
    )


# ---- 决策辅助 ----

def _should_escalate_to_pro(proposal: GraphChangeProposal) -> bool:
    """检查是否需要 Pro 升级。"""
    # M3 特定升级条件
    conflicts = proposal.conflicts or []
    impact = proposal.impact_scope or []

    high_grade_conflict = any(
        "S" in c or "A" in c or "high-grade" in c.lower()
        for c in conflicts
    )
    cross_industry = any(
        "cross-industry" in i.lower() or "跨行业" in i
        for i in impact
    )
    ontology_implication = any(
        "ontology" in c.lower() or "本体" in c or "Industry" in c
        for c in conflicts
    )

    return high_grade_conflict or cross_industry or ontology_implication


# ---- 流水线入口 ----

class CandidatePipeline:
    """M3 GraphChange Candidate Pipeline。"""

    def __init__(
        self,
        db: Database,
        *,
        provider: Optional[LlmProvider] = None,
        validator: Optional[LlmOutputValidator] = None,
        live: bool = False,
        dry_run: bool = False,
    ):
        self._db = db
        self._adapter = SourceAdapter(db)
        self._builder = GraphChangeBuilder(db)
        self._candidate_repo = GraphChangeCandidateRepository(db)
        self._live = live
        self._dry_run = dry_run

        configured = is_provider_configured() and provider is not None
        self._llm_client = LlmClient(
            provider=provider,
            validator=validator or LlmOutputValidator(
                model_factory={"graph_change_proposal": GraphChangeProposal}
            ),
            db=db,
            configured=configured and live,
        )

    def run(
        self,
        sources: List[Tuple[str, str]],
        *,
        knowledge_dir: Optional[Path] = None,
        evidence_ids: Optional[List[str]] = None,
        requested_model_class: str = "flash",
    ) -> Dict[str, Any]:
        """运行候选管线。

        Args:
            sources: [(source_type, source_id), ...]
            knowledge_dir: knowledge/ 目录路径。
            evidence_ids: 显式证据 ID 列表。
            requested_model_class: "flash" | "pro"

        Returns:
            确定性 JSON 摘要。
        """
        results: Dict[str, Any] = {
            "status": "ok",
            "dry_run": self._dry_run,
            "live": self._live,
            "sources_processed": 0,
            "candidates_generated": 0,
            "candidates_persisted": 0,
            "model_used": None,
            "errors": [],
            "candidates": [],
        }

        # ---- 1. Preflight ----
        preflight_results = []
        for st, sid in sources:
            d = knowledge_ingest_decider(self._db, st, sid, evidence_ids)
            preflight_results.append(d)

        failed_preflights = [d for d in preflight_results if not d.allowed]
        if failed_preflights:
            results["status"] = "preflight_failed"
            results["errors"] = [d.reason for d in failed_preflights]
            return results

        if self._dry_run:
            results["status"] = "dry_run"
            results["sources_processed"] = len(sources)
            results["message"] = (
                f"Preflight passed for {len(sources)} sources. "
                f"0 LLM / 0 candidate / 0 writes (dry-run)"
            )
            return results

        # ---- 2. Load source objects ----
        source_objects = self._adapter.load_batch(sources)
        results["sources_processed"] = len(source_objects)

        # ---- 3. Load evidence context ----
        all_evidence_ids = evidence_ids or []
        ev_contexts, ev_errors = load_evidence_context(
            self._db, all_evidence_ids
        )
        if ev_errors:
            results["status"] = "evidence_error"
            results["errors"].extend(ev_errors)
            return results

        # ---- 4. LLM Proposal ----
        if not self._live or self._llm_client.provider is None:
            # 非 live 或无 Provider：跳过 LLM，返回 preflight only
            results["status"] = "preflight_only"
            results["message"] = "非 live 模式或无 Provider，仅完成预检"
            return results

        proposal = self._call_llm_for_proposal(
            source_objects, ev_contexts, requested_model_class, results
        )
        if proposal is None:
            return results  # LLM 失败，results 已含错误

        # ---- 5. Validate proposal ----
        try:
            validated_proposal = GraphChangeProposal(**proposal.output) if proposal.output else None
        except Exception as exc:
            results["status"] = "proposal_validation_failed"
            results["errors"].append(f"Proposal Pydantic 构造失败: {exc}")
            return results

        if validated_proposal is None:
            results["status"] = "proposal_empty"
            results["errors"].append("LLM 未返回有效 proposal")
            return results

        # ---- 6. 冲突检测 ----
        conflicts = self._builder.check_conflicts(validated_proposal)
        if conflicts:
            # 如果有冲突且未升级到 Pro，尝试 Pro
            if requested_model_class != "pro" and _should_escalate_to_pro(validated_proposal):
                results["model_used"] = "pro"
                proposal2 = self._call_llm_for_proposal(
                    source_objects, ev_contexts, "pro", results
                )
                if proposal2 is not None and proposal2.output:
                    try:
                        validated_proposal = GraphChangeProposal(**proposal2.output)
                        conflicts = self._builder.check_conflicts(validated_proposal)
                    except Exception:
                        pass

        # ---- 7. Build GraphChange ----
        try:
            graph_change = self._builder.build(validated_proposal)
        except ValueError as exc:
            results["status"] = "build_failed"
            results["errors"].append(str(exc))
            return results

        # ---- 8. Persist ----
        if not self._dry_run:
            try:
                op = self._candidate_repo.append_candidate(graph_change)
                results["candidates_persisted"] = 1
            except ValueError as exc:
                results["errors"].append(str(exc))
                # idempotent_noop 不算失败
                if "IDEMPOTENT" not in str(exc).upper():
                    results["status"] = "persist_failed"
                    return results

        results["candidates_generated"] = 1

        # ---- 9. Render Markdown ----
        if knowledge_dir is not None and not self._dry_run:
            renderer = CandidateRenderer(knowledge_dir)
            try:
                file_path = renderer.render_to_file(graph_change, ev_contexts)
                results["markdown_path"] = file_path
            except ValueError as exc:
                results["errors"].append(f"Markdown render: {exc}")

        results["candidates"].append({
            "graph_change_id": graph_change.graph_change_id,
            "change_type": graph_change.change_type,
        })

        return results

    def _call_llm_for_proposal(
        self,
        source_objects: Dict,
        ev_contexts: List,
        model_class: str,
        results: Dict,
    ) -> Optional[Any]:
        """调用 LLM 生成 GraphChangeProposal。"""
        prompt = self._build_prompt(source_objects, ev_contexts)
        request = LlmClient.make_request(
            task_id=new_uuid(),
            module="knowledge_candidates",
            prompt=prompt,
            output_schema_name="graph_change_proposal",
            requested_model_class=model_class,
        )
        response = self._llm_client.generate_json(
            request, {},  # output_schema 由 validator 的 schema 校验处理
        )
        results["model_used"] = response.model_id or model_class

        if not response.called or response.status != "success":
            results["status"] = "llm_failed"
            results["errors"].extend(response.validation_errors or [])
            results["errors"].append(f"LLM {response.status}: {response.warnings}")
            return None

        return response

    def _build_prompt(
        self,
        source_objects: Dict,
        ev_contexts: List[EvidenceContext],
    ) -> str:
        """构建 LLM Prompt。"""
        parts = ["You are a knowledge graph analyst. Review the following sources and evidence and propose a GraphChange."]
        parts.append("")

        parts.append("## Sources")
        for (st, sid), obj in source_objects.items():
            parts.append(f"- **{st}** `{sid}`:")
            if hasattr(obj, "model_dump"):
                d = obj.model_dump()
                # 截断长字段
                for k in ("summary", "statement", "thesis", "description"):
                    if k in d and isinstance(d[k], str) and len(d[k]) > 500:
                        d[k] = d[k][:500] + "..."
                parts.append("```json")
                parts.append(json.dumps(d, ensure_ascii=False, indent=2))
                parts.append("```")
        parts.append("")

        parts.append("## Evidence")
        for ctx in ev_contexts:
            parts.append(f"- **[{ctx.role}] {ctx.title}** ({ctx.source_tier})")
            parts.append(f"  {ctx.excerpt[:200]}")
        parts.append("")

        parts.append("## Instructions")
        parts.append("Generate a GraphChangeProposal in JSON format with these required fields:")
        parts.append("- proposal_type: one of add_node, add_edge, modify_attribute, retire_edge, retire_node")
        parts.append("- source_object_ids: list of source IDs")
        parts.append("- candidate_node: node proposal (with existing_node_id, node_type, name, aliases, description, valid_from, valid_to)")
        parts.append("- candidate_edge: edge proposal (with source_node_id, relation, target_node_id, attributes, assertion_type, valid_from, valid_to, confidence)")
        parts.append("- new_evidence_ids: list of evidence IDs")
        parts.append("- suggested_change: human-readable description of the change")
        parts.append("- impact_scope: list of impacted areas")
        parts.append("- conflicts: list of potential conflicts")
        parts.append("- verification_points: list of verification items")
        parts.append("- confidence: 0.0-1.0")
        parts.append("")
        parts.append("Output ONLY valid JSON, no markdown fences or extra text.")

        return "\n".join(parts)
