"""主题发现流水线（Theme Discovery Pipeline）：图驱动 + 关键词扫描 + 证据驱动。

Phase 6A ThemeDiscoveryPipeline — 确定性只读，零 LLM / 零 Provider / 零 Network。

工程约束：
- 禁止私有 Graph API 调用（_query_graph_locked 禁用）
- 禁止直接 SQL（self.db._conn.execute 禁用）
- 仅使用 GraphQueryService 公开 API（query_graph）
- evidence_driven / peer_diffusion 模式下若无可用的公开接口，优雅降级
- Lifecycle 仅使用 THEME_LIFECYCLE_STATES:
  forming / supported / weakening / invalidated / uncertain
- as_of 必填

阶段顺序（R1-5）：
  1. Scan Triggers — 用公开 API 扫描触发信号
  2. Cluster Triggers — 将触发信号聚类为主题假设
  3. Evidence Reload — 从权威 Evidence 存储重载并校验
  4. Support/Counter/Limitations — 填充证据分析字段
  5. Detect Lifecycle — 基于已验证证据检测生命周期
  6. Compute Metrics — 计算每个主题的 12 项 ResearchSortMetrics
  7. Determine Status — 设置 result.status
  8. Render Report — 生成结构化 Markdown 报告

禁止：
  - _query_graph_locked（私有 Graph API）
  - self.db._conn.execute（直接 SQL）
  - 任何 LLM / Provider / Network 调用
  - 原始图引用作为 support（仅权威 Evidence 存储）
  - MODEL_INFERENCE 作为 support
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

from research_os.theme_discovery import (
    DISCOVERY_MODES,
    THEME_LIFECYCLE_STATES,
    ResearchSortMetrics,
    ThemeDiscoveryResult,
    ThemeHypothesis,
    ThemeTrigger,
)
from research_os.industry_research.evidence_adapter import validate_evidence_ids_chain
from research_os.utils.id import content_sha256, new_uuid
from research_os.utils.time import now_iso, validate_iso


class ThemeDiscoveryPipeline:
    """主题发现流水线（确定性核心，零 LLM）。

    阶段顺序（R1-5）：
      1. Scan Triggers — 用公开 API 扫描触发信号
      2. Cluster Triggers — 将触发信号聚类为主题假设
      3. Evidence Reload — 从权威 Evidence 存储重载并校验
      4. Support/Counter/Limitations — 填充证据分析字段
      5. Detect Lifecycle — 基于已验证证据检测生命周期
      6. Compute Metrics — 计算每个主题的 12 项 ResearchSortMetrics
      7. Determine Status — 设置 result.status
      8. Render Report — 生成结构化 Markdown 报告

    禁止：
      - _query_graph_locked（私有 Graph API）
      - self.db._conn.execute（直接 SQL）
      - 任何 LLM / Provider / Network 调用
      - 原始图引用作为 support（仅权威 Evidence 存储）
      - MODEL_INFERENCE 作为 support
    """

    def __init__(
        self,
        project_root: str | Path = ".",
        db: Any = None,
        llm_client: Any = None,
    ):
        self.project_root = Path(project_root)
        self.db = db
        self.llm_client = None  # 确定性：不使用 LLM

    # ═══════════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════════

    def run(self, request: Dict[str, Any]) -> ThemeDiscoveryResult:
        """执行主题发现流水线。

        request 必须包含 as_of（ISO-8601）；可选 discovery_mode / industry_ids / keywords。
        """
        as_of = request.get("as_of")
        if not as_of or not validate_iso(str(as_of)):
            return ThemeDiscoveryResult(
                status="failed", task_id=request.get("task_id", ""),
                run_id=new_uuid(), as_of=str(as_of or ""),
                discovery_mode=request.get("discovery_mode", "graph_based"),
                exit_code=1, message="as_of 必填且必须为合法 ISO-8601 时间",
                missing_data=["as_of_missing_or_invalid"],
                model_route={"mode": "deterministic_fallback", "llm_called": False},
            )

        discovery_mode = request.get("discovery_mode", "graph_based")
        if discovery_mode not in DISCOVERY_MODES:
            discovery_mode = "graph_based"

        industry_ids: List[str] = list(request.get("industry_ids") or [])
        keywords: List[str] = list(request.get("keywords") or [])
        task_id: str = request.get("task_id", "")
        run_id: str = new_uuid()
        as_of_str = str(as_of)

        result = ThemeDiscoveryResult(
            status="running", task_id=task_id, run_id=run_id,
            as_of=as_of_str, discovery_mode=discovery_mode,
        )

        # ── Stage 1: Scan Triggers ──
        triggers = self._scan_triggers(as_of_str, discovery_mode, industry_ids, keywords)
        result.triggers = triggers

        # capability_unavailable → degraded
        if discovery_mode in ("evidence_driven", "peer_diffusion"):
            result.status = "degraded"
            result.data_degraded = True
            result.exit_code = 3
            result.message = (
                f"discovery_mode={discovery_mode} 无可用公开 API 接口，"
                "流水线已降级。部分数据可能不完整。"
            )
            result.missing_data.append(
                f"capability_unavailable:{discovery_mode}")
            result.model_route = {"mode": "deterministic_fallback", "llm_called": False}
            result.markdown = self._render_report(result)
            return result

        # no_eligible_evidence → insufficient_evidence
        if not triggers:
            result.status = "insufficient_evidence"
            result.exit_code = 4
            result.message = f"No triggers found for mode={discovery_mode}"
            result.missing_data.append("no_triggers_found")
            result.model_route = {"mode": "deterministic_fallback", "llm_called": False}
            result.markdown = self._render_report(result)
            return result

        # ── Stage 2: Cluster triggers → ThemeHypothesis ──
        themes = self._cluster_triggers(triggers, as_of_str)

        # ── Stage 3: Evidence Reload + Stage 4: Support/Counter/Limitations ──
        for theme in themes:
            self._populate_evidence_analysis(theme, as_of_str)

        # R2-13: propagate db-unavailable to result.missing_data
        if self.db is None or any(
            getattr(t, "_db_unavailable", False) for t in themes
        ):
            if "authoritative_evidence_store_unavailable" not in result.missing_data:
                result.missing_data.append("authoritative_evidence_store_unavailable")

        # ── Stage 5: Detect Lifecycle（基于已验证证据）──
        for theme in themes:
            theme.lifecycle_state = self._detect_lifecycle(theme)

        # ── Stage 6: Compute Metrics ──
        sort_metrics: Dict[str, ResearchSortMetrics] = {}
        for theme in themes:
            sort_metrics[theme.hypothesis_id] = self._compute_metrics(theme)

        # ── Stage 7: Write themes + metrics, determine status BEFORE render ──
        result.themes = themes
        result.sort_metrics = sort_metrics

        # Status mapping (R1-7 + R2-9 + R3-1):
        # capability_unavailable→degraded (handled earlier)
        # no_eligible_evidence→insufficient_evidence
        # eligible evidence exists + deterministic-only (llm_called=false)→partial_success
        has_eligible_support = any(
            bool(theme.supporting_evidence_ids) for theme in themes)
        if not themes:
            result.status = "insufficient_evidence"
        elif not has_eligible_support:
            result.status = "insufficient_evidence"
        else:
            result.status = "partial_success"  # deterministic-only, no llm semantic enrichment
        result.model_route = {"mode": "deterministic_fallback", "llm_called": False}
        result.exit_code = 0
        result.message = f"Discovered {len(themes)} themes (mode={discovery_mode})"

        # ── Stage 8: Render Report ──
        result.markdown = self._render_report(result)
        return result

    # ═══════════════════════════════════════════════════════════════
    # Stage 1: Scan Triggers
    # ═══════════════════════════════════════════════════════════════

    def _scan_triggers(
        self, as_of: str, discovery_mode: str,
        industry_ids: List[str], keywords: List[str],
    ) -> List[ThemeTrigger]:
        """扫描触发信号 —— 仅使用公开 API。"""
        if discovery_mode == "graph_based":
            return self._triggers_from_graph(as_of, industry_ids)
        if discovery_mode == "keyword_sweep":
            return self._triggers_from_keywords(keywords, industry_ids, as_of)
        # evidence_driven / peer_diffusion: 无公开 API，优雅降级
        return []  # 由 run() 检测并设置 degraded 状态

    def _triggers_from_graph(
        self, as_of: str, industry_ids: List[str],
    ) -> List[ThemeTrigger]:
        """使用 GraphQueryService.query_graph() 公开 API 扫描跨行业关联。"""
        triggers: List[ThemeTrigger] = []
        if self.db is None or not industry_ids:
            return triggers

        try:
            from research_os.knowledge.query import GraphQueryService
            svc = GraphQueryService(self.db)
        except ImportError:
            return triggers
        except Exception:
            return triggers

        for ind_id in industry_ids:
            try:
                qr = svc.query_graph(root_node_id=ind_id, as_of=as_of,
                                     max_depth=1, direction="both")
            except Exception:
                continue

            cross_inds: Set[str] = set()
            relations: Set[str] = set()
            node_ids: List[str] = []
            for nw in qr.nodes:
                p = nw.get("payload", {})
                nid = p.get("node_id", "")
                if nid:
                    node_ids.append(nid)
                for ni in (p.get("industry_ids") or []):
                    if ni != ind_id:
                        cross_inds.add(ni)
            for ew in qr.edges:
                rel = ew.get("payload", {}).get("relation", "")
                if rel:
                    relations.add(rel)

            if cross_inds or relations:
                desc_parts: List[str] = []
                if cross_inds:
                    desc_parts.append(f"跨行业关联: {', '.join(sorted(cross_inds)[:5])}")
                if relations:
                    desc_parts.append(f"关系类型: {', '.join(sorted(relations)[:5])}")
                trig_canonical = "|".join([
                    "graph_anomaly",
                    ind_id.lower().strip(),
                    ",".join(sorted({ind_id} | cross_inds)),
                    ",".join(sorted(node_ids)),
                    ",".join(sorted(qr.evidence_ids)),
                    ",".join(sorted(relations)),
                    as_of,
                ])
                triggers.append(ThemeTrigger(
                    trigger_id="trig:" + content_sha256(trig_canonical),
                    trigger_type="graph_anomaly", keyword=ind_id,
                    industry_ids=sorted({ind_id} | cross_inds),
                    evidence_ids=list(qr.evidence_ids),
                    graph_node_ids=node_ids,
                    description="; ".join(desc_parts) if desc_parts else f"Graph trigger from {ind_id}",
                    strength=min(0.3 + 0.15 * len(cross_inds) + 0.1 * len(relations), 0.95),
                    first_seen_at=as_of, last_seen_at=as_of,
                ))
        return triggers

    def _triggers_from_keywords(
        self, keywords: List[str], industry_ids: List[str], as_of: str,
    ) -> List[ThemeTrigger]:
        """确定性关键词匹配。有 industry_ids + db 时通过 GraphQueryService 在图节点
        payload 中搜索关键词；否则直接为每个关键词生成触发信号。"""
        triggers: List[ThemeTrigger] = []
        if not keywords:
            return triggers

        if industry_ids and self.db is not None:
            try:
                from research_os.knowledge.query import GraphQueryService
                svc = GraphQueryService(self.db)
                kw_lower = {kw.lower() for kw in keywords}
                for ind_id in industry_ids:
                    try:
                        qr = svc.query_graph(root_node_id=ind_id, as_of=as_of,
                                             max_depth=1, direction="both")
                    except Exception:
                        continue
                    matched_kws: Set[str] = set()
                    matched_nodes: List[str] = []
                    for nw in qr.nodes:
                        p = nw.get("payload", {})
                        nid = p.get("node_id", "")
                        if any(kw in str(p).lower() for kw in kw_lower):
                            matched_kws.update(
                                kw for kw in kw_lower if kw in str(p).lower())
                            if nid and nid not in matched_nodes:
                                matched_nodes.append(nid)
                    if matched_kws:
                        trig_canonical = "|".join([
                            "keyword_sweep",
                            ",".join(sorted(matched_kws)),
                            ind_id,
                            ",".join(sorted(matched_nodes)),
                            ",".join(sorted(qr.evidence_ids)),
                            as_of,
                        ])
                        triggers.append(ThemeTrigger(
                            trigger_id="trig:" + content_sha256(trig_canonical),
                            trigger_type="keyword_sweep",
                            keyword=", ".join(sorted(matched_kws)),
                            industry_ids=[ind_id],
                            evidence_ids=list(qr.evidence_ids),
                            graph_node_ids=matched_nodes,
                            description=f"关键词命中: {', '.join(sorted(matched_kws))} (行业 {ind_id})",
                            strength=min(0.3 + 0.15 * len(matched_kws), 0.85),
                            first_seen_at=as_of, last_seen_at=as_of,
                        ))
            except ImportError:
                pass
            except Exception:
                pass
        else:
            for kw in keywords:
                trig_canonical = "|".join([
                    "keyword_sweep",
                    kw.lower().strip(),
                    ",".join(sorted(industry_ids)),
                    as_of,
                ])
                triggers.append(ThemeTrigger(
                    trigger_id="trig:" + content_sha256(trig_canonical),
                    trigger_type="keyword_sweep", keyword=kw,
                    industry_ids=list(industry_ids),
                    description=f"关键词触发: {kw}",
                    strength=0.25, first_seen_at=as_of, last_seen_at=as_of,
                ))
        return triggers

    # ═══════════════════════════════════════════════════════════════
    # Stage 2: Cluster Triggers → ThemeHypothesis
    # ═══════════════════════════════════════════════════════════════

    def _cluster_triggers(
        self, triggers: List[ThemeTrigger], as_of: str,
    ) -> List[ThemeHypothesis]:
        """按行业重叠 + 关键词相似度将 trigger 聚类为主题假设。"""
        if not triggers:
            return []

        themes: List[ThemeHypothesis] = []
        assigned: Set[str] = set()

        for t0 in triggers:
            if t0.trigger_id in assigned:
                continue
            cluster = [t0]
            assigned.add(t0.trigger_id)
            t0_inds = set(t0.industry_ids)
            t0_kw = (t0.keyword or "").lower()

            for tj in triggers:
                if tj.trigger_id in assigned:
                    continue
                tj_inds = set(tj.industry_ids)
                tj_kw = (tj.keyword or "").lower()
                if (t0_inds & tj_inds) or (
                    t0_kw and tj_kw
                    and (t0_kw == tj_kw or t0_kw in tj_kw or tj_kw in t0_kw)
                ):
                    cluster.append(tj)
                    assigned.add(tj.trigger_id)

            themes.append(self._build_hypothesis(cluster, as_of))

        return self._merge_singletons(themes)

    def _build_hypothesis(
        self, cluster: List[ThemeTrigger], as_of: str,
    ) -> ThemeHypothesis:
        """从 trigger 聚类构建 ThemeHypothesis。"""
        all_inds: Set[str] = set()
        all_kws: List[str] = []
        all_evidence: Set[str] = set()
        all_nodes: Set[str] = set()
        for t in cluster:
            all_inds.update(t.industry_ids)
            if t.keyword and t.keyword not in all_kws:
                all_kws.append(t.keyword)
            all_evidence.update(t.evidence_ids)
            all_nodes.update(t.graph_node_ids)

        cross_count = len(all_inds)
        name = self._derive_name(cluster, sorted(all_inds))
        statement = self._derive_statement(name, len(cluster), cross_count)
        confidence = self._cluster_confidence(cluster)

        # R4-4: canonical hypothesis hash = sorted trigger_ids + normalized theme name + sorted industry_ids
        sorted_trigger_ids = sorted([t.trigger_id for t in cluster])
        normalized_name = name.lower().strip()
        sorted_inds_str = ",".join(sorted(all_inds))
        hypo_canonical = "|".join([
            ",".join(sorted_trigger_ids),
            normalized_name,
            sorted_inds_str,
        ])

        return ThemeHypothesis(
            hypothesis_id="hyp:" + content_sha256(hypo_canonical),
            theme_name=name, statement=statement, claim_type="HYPOTHESIS",
            lifecycle_state="forming", triggers=list(cluster),
            cross_industry_count=cross_count,
            # R2-10: start empty; only populate after authoritative reload
            supporting_evidence_ids=[],
            industry_mapping=[{"industry_id": i, "weight": 1.0}
                              for i in sorted(all_inds)],
            related_entity_ids=sorted(all_nodes),
            confidence=confidence, first_observed_at=as_of, updated_at=as_of,
            generated_by="deterministic_fallback", model_route="deterministic_fallback",
        )

    # ═══════════════════════════════════════════════════════════════
    # Stage 5: Detect Lifecycle（基于已验证证据）
    # ═══════════════════════════════════════════════════════════════

    def _detect_lifecycle(self, theme: ThemeHypothesis) -> str:
        """确定性生命周期检测（仅 THEME_LIFECYCLE_STATES 词汇）。

        规则（按优先级，R2-11 修正）：
          1. 有权威 counter evidence → weakening（覆盖 support）
          2. 有权威 supporting evidence → supported
          3. 有 verified actual invalidation → invalidated
          4. 有 trigger 但无 qualifying evidence → forming
          5. 其余 → uncertain

        invalidating_conditions ≠ invalidated；不因存在 invalidating_conditions
        即判定为 invalidated。
        """
        # R2-11: counter evidence OVERRIDES support — check counter first.
        # Has authoritative counter evidence → weakening (even if support exists)
        if theme.counter_evidence_ids:
            return "weakening"
        # Has authoritative supporting evidence (validated via evidence chain)
        if theme.supporting_evidence_ids:
            return "supported"
        # verified actual invalidation: requires authoritative external source
        # (not reachable in deterministic-only mode without explicit Evidence flag)
        # Has trigger but no qualifying evidence
        if theme.triggers:
            return "forming"
        return "uncertain"

    # ═══════════════════════════════════════════════════════════════
    # Stages 3-4: Evidence Reload + Support/Counter/Limitations
    # ═══════════════════════════════════════════════════════════════

    def _populate_evidence_analysis(self, theme: ThemeHypothesis, as_of: str) -> None:
        """填充 evidence 分析字段（S2-3 权威重载 + S2-4 counter_evidence/limitations 分离）。

        supporting_evidence_ids, counter_evidence_ids — 仅来自 Database.get("evidence", eid)
        权威重载 + eligibility 校验。counter_evidence 仅来自权威 Evidence。
        Weak signal / trigger count → limitations，NOT counter_evidence。
        """
        # ── S2-3: supporting_evidence_ids 权威重载 ──
        ev_set: Set[str] = set()
        for t in theme.triggers:
            ev_set.update(t.evidence_ids)
        all_candidate_ids = sorted(ev_set)

        # R1-20 + R2-13: db=None → fail-closed：清空 supporting_evidence_ids，
        # 添加 authoritative_evidence_store_unavailable limitation。
        if self.db is None:
            theme.supporting_evidence_ids = []
            theme.limitations.append("authoritative_evidence_store_unavailable")
            # R2-13: also record in result.missing_data (set via _db_unavailable flag)
            theme._db_unavailable = True  # type: ignore[attr-defined]
        elif all_candidate_ids:
            chain = validate_evidence_ids_chain(all_candidate_ids, self.db, as_of)
            valid_raw = chain["valid"]

            # R1-21: industry_tags intersection — 若 Evidence 含 industry_tags
            # 且 theme 有 industry_mapping，仅保留 industry_tags 与
            # theme industry_ids 有交集的 evidence。
            if valid_raw and theme.industry_mapping:
                theme_ind_ids = {
                    im.get("industry_id", "") for im in theme.industry_mapping
                    if im.get("industry_id")
                }
                if theme_ind_ids:
                    filtered: List[str] = []
                    for eid in valid_raw:
                        try:
                            ev = self.db.get("evidence", eid)
                        except Exception:
                            continue
                        if ev is None:
                            continue
                        ev_tags = ev.get("industry_tags")
                        if ev_tags is None:
                            # 无 industry_tags → 无法判定，保留
                            filtered.append(eid)
                        elif isinstance(ev_tags, list) and theme_ind_ids.intersection(ev_tags):
                            filtered.append(eid)
                        # else: industry_tags 存在但无交集 → 排除
                    theme.supporting_evidence_ids = filtered
                else:
                    theme.supporting_evidence_ids = valid_raw
            else:
                theme.supporting_evidence_ids = valid_raw

            # 缺失/不合格证据记录为 limitations
            if chain["missing"] or chain["invalid"]:
                for eid in chain["missing"]:
                    theme.limitations.append(
                        f"evidence {eid} 不存在（图谱指针悬挂）")
                for eid in chain["invalid"]:
                    rs = chain["reasons"].get(eid, ["资格校验未通过"])
                    theme.limitations.append(
                        f"evidence {eid} 资格校验未通过: {'; '.join(rs)}")
        else:
            theme.supporting_evidence_ids = all_candidate_ids

        # ── supporting_factors ──
        factors: List[str] = []
        tt_set = {t.trigger_type for t in theme.triggers}
        if "graph_anomaly" in tt_set:
            factors.append("知识图谱跨行业关联信号")
        if "keyword_sweep" in tt_set:
            factors.append("关键词扫描命中")
        all_inds: Set[str] = set()
        for t in theme.triggers:
            all_inds.update(t.industry_ids)
        if len(all_inds) >= 2:
            factors.append(f"覆盖 {len(all_inds)} 个不同行业")
        valid_ev = theme.supporting_evidence_ids
        if valid_ev:
            factors.append(f"关联 {len(valid_ev)} 条权威证据")
        theme.supporting_factors = factors or theme.supporting_factors

        # ── S2-4: counter_evidence 仅来自权威 Evidence ──
        # counter_evidence 字段保留但仅在实际有权威反证时填充；此处确定性流水线不生成
        if not theme.counter_evidence:
            theme.counter_evidence = []

        # ── S2-4: limitations（弱信号/trigger 数量 → limitations，NOT counter_evidence）──
        limitations: List[str] = list(theme.limitations)  # 保留已有的（如证据悬挂）
        if len(theme.triggers) <= 1:
            limitations.append("触发信号数量不足（仅 1 个），可能是噪声")
        if not ev_set:
            limitations.append("无直接关联证据")
        weak = [t for t in theme.triggers if t.strength < 0.4]
        if weak:
            limitations.append(f"{len(weak)} 个 trigger strength < 0.4，信号偏弱")
        theme.limitations = limitations

        # ── counter_evidence_ids（外部系统补充，此处保持空）──
        if not theme.counter_evidence_ids:
            theme.counter_evidence_ids = []

        # ── industry_mapping ──
        if not theme.industry_mapping:
            theme.industry_mapping = [
                {"industry_id": i, "weight": 1.0} for i in sorted(all_inds)]

        # ── related_entity_ids ──
        if not theme.related_entity_ids:
            nodes: Set[str] = set()
            for t in theme.triggers:
                nodes.update(t.graph_node_ids)
            theme.related_entity_ids = sorted(nodes)

        # ── invalidating_conditions ──
        if not theme.invalidating_conditions:
            # R2-12: prospective wording ("若后续..."), not present-tense claims.
            inv: List[str] = []
            if len(theme.triggers) <= 1:
                inv.append("若后续 30 天内无新增触发信号，主题可能失效")
            if not ev_set:
                inv.append("若后续 30 天内仍无证据关联，主题可能失效")
            theme.invalidating_conditions = inv

        # ── open_questions ──
        if not theme.open_questions:
            qs: List[str] = [
                "该主题的驱动因素是结构性还是周期性？"]
            if len(all_inds) >= 2:
                qs.append(f"跨行业传导机制是什么？（涉及 {len(all_inds)} 个行业）")
            qs.append("是否有可量化的市场规模数据支撑？")
            theme.open_questions = qs

    # ═══════════════════════════════════════════════════════════════
    # Stage 6: Compute Metrics（全部 12 项 ResearchSortMetrics）
    # ═══════════════════════════════════════════════════════════════

    def _compute_metrics(self, theme: ThemeHypothesis) -> ResearchSortMetrics:
        """计算单个主题的 ResearchSortMetrics（12 个字段全部填充）。"""
        ev_vol = len(theme.supporting_evidence_ids)
        n_trig = len(theme.triggers)
        cross = theme.cross_industry_count

        # evidence_trend
        trend = self._evidence_trend(theme)

        # company_adoption
        company_adoption = len(theme.company_ids) or len(
            [e for e in theme.related_entity_ids if "company" in e.lower()])

        # policy_support
        policy_kw = {"政策", "policy", "regulation", "监管", "补贴", "subsidy"}
        has_pol = any(
            t.keyword and any(pk in (t.keyword or "").lower() for pk in policy_kw)
            for t in theme.triggers)
        policy_support = "supportive" if has_pol else "neutral"

        # market_attention
        if n_trig >= 5 or ev_vol >= 10:
            market_attention = "high"
        elif n_trig >= 2 or ev_vol >= 3:
            market_attention = "medium"
        else:
            market_attention = "low"

        # controversy_level（S2-4: 仅基于 counter_evidence_ids 权威反证）
        n_counter = len(theme.counter_evidence_ids)
        controversy_level = "high" if n_counter >= 2 else ("medium" if n_counter >= 1 else "low")

        # research_priority
        research_priority = min(
            0.3 * (ev_vol / max(1, 10)) + 0.3 * theme.confidence
            + 0.2 * min(cross / 5.0, 1.0)
            + 0.2 * (1.0 if theme.lifecycle_state == "supported" else 0.5), 1.0)

        # novelty
        _nov_map = {"forming": 0.85, "supported": 0.60, "weakening": 0.30,
                    "invalidated": 0.10, "uncertain": 0.50}
        novelty = _nov_map.get(theme.lifecycle_state, 0.50)

        # evidence_density
        evidence_density = ev_vol / max(n_trig, 1)

        # theme_relevance
        theme_relevance = theme.confidence * min(cross / 3.0, 1.0)

        # uncertainty
        _unc_map = {"uncertain": 0.90, "forming": 0.70, "weakening": 0.50,
                    "invalidated": 0.20, "supported": 0.30}
        uncertainty = _unc_map.get(theme.lifecycle_state, 0.50)

        return ResearchSortMetrics(
            evidence_volume=ev_vol, evidence_trend=trend,
            cross_industry_count=cross, company_adoption=company_adoption,
            policy_support=policy_support, market_attention=market_attention,
            controversy_level=controversy_level,
            research_priority=round(research_priority, 2),
            novelty=round(novelty, 2),
            evidence_density=round(evidence_density, 2),
            theme_relevance=round(theme_relevance, 2),
            uncertainty=round(uncertainty, 2),
        )

    def _evidence_trend(self, theme: ThemeHypothesis) -> str:
        """基于 trigger 时间戳启发式判断证据趋势（rising/falling/stable）。"""
        stamps: List[datetime] = []
        for t in theme.triggers:
            for attr in ("first_seen_at", "last_seen_at"):
                val = getattr(t, attr, None)
                if val:
                    try:
                        stamps.append(
                            datetime.fromisoformat(str(val).replace("Z", "+00:00")))
                    except (ValueError, TypeError):
                        pass
        if len(stamps) < 2:
            return "stable"
        stamps.sort()
        mid = stamps[0] + (stamps[-1] - stamps[0]) / 2
        later = [s for s in stamps if s >= mid]
        earlier = [s for s in stamps if s < mid]
        if len(later) > len(earlier):
            return "rising"
        if len(later) < len(earlier):
            return "falling"
        return "stable"

    # ═══════════════════════════════════════════════════════════════
    # Stage 8: Render Report
    # ═══════════════════════════════════════════════════════════════

    def _render_report(self, result: ThemeDiscoveryResult) -> str:
        """生成结构化 Markdown 报告（确定性渲染，零 LLM）。"""
        lines: List[str] = []

        # ── 头部 ──
        lines.extend([
            "# 主题发现报告", "",
            f"**Run ID**: `{result.run_id}`",
            f"**Task ID**: `{result.task_id}`",
            f"**As Of**: {result.as_of}",
            f"**Status**: {result.status}",
            f"**Discovery Mode**: {result.discovery_mode}", "",
        ])

        # ── 免责声明 ──
        lines.extend([
            "> ⚠️ **免责声明**：主题发现（theme discovery）不等同于股票推荐"
            "（stock picking）。",
            "> 本报告仅识别跨行业关联与潜在投资主题，不构成任何买入/卖出/持仓建议。",
            "> 任何投资决策应基于独立研究并结合个人风险承受能力做出。", "",
        ])

        # ── 警告与缺失数据 ──
        if result.warnings:
            lines.append("## 警告"); lines.append("")
            for w in result.warnings:
                lines.append(f"- ⚠️ {w}")
            lines.append("")
        if result.missing_data:
            lines.append("## 缺失数据"); lines.append("")
            for md in result.missing_data:
                lines.append(f"- 📭 {md}")
            lines.append("")

        # ── 排序指标表 ──
        if result.sort_metrics:
            lines.extend([
                "## 主题排序指标", "",
                "| 主题 | 证据量 | 趋势 | 跨行业 | 公司采纳 | "
                "政策 | 关注度 | 争议 | 优先级 | 新颖度 | 密度 | 相关性 | 不确定性 |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
            ])
            for theme in result.themes:
                m = result.sort_metrics.get(theme.hypothesis_id)
                if m is None:
                    continue
                name = theme.theme_name or theme.hypothesis_id[:12]
                lines.append(
                    f"| {name} | {m.evidence_volume} | {m.evidence_trend} "
                    f"| {m.cross_industry_count} | {m.company_adoption} "
                    f"| {m.policy_support} | {m.market_attention} "
                    f"| {m.controversy_level} | {m.research_priority:.2f} "
                    f"| {m.novelty:.2f} | {m.evidence_density:.2f} "
                    f"| {m.theme_relevance:.2f} | {m.uncertainty:.2f} |")
            lines.append("")

        # ── 主题详情 ──
        LC_EMOJI = {"forming": "🌱", "supported": "✅", "weakening": "⚠️",
                    "invalidated": "🚫", "uncertain": "❓"}
        if result.themes:
            lines.extend(["## 发现的主题", ""])
            for i, theme in enumerate(result.themes, 1):
                emoji = LC_EMOJI.get(theme.lifecycle_state, "❓")
                lines.extend([
                    f"### {emoji} 主题 {i}: {theme.theme_name}", "",
                    f"- **Hypothesis ID**: `{theme.hypothesis_id}`",
                    f"- **Statement**: {theme.statement}",
                    f"- **Lifecycle**: {theme.lifecycle_state}",
                    f"- **Confidence**: {theme.confidence:.2f}",
                    f"- **Cross-Industry Count**: {theme.cross_industry_count}",
                    f"- **Claim Type**: {theme.claim_type}",
                    f"- **Generated By**: {theme.generated_by}", "",
                ])
                if theme.supporting_factors:
                    lines.append("**支持因素**:")
                    for sf in theme.supporting_factors:
                        lines.append(f"  - ✅ {sf}")
                    lines.append("")
                if theme.counter_evidence:
                    lines.append("**反证/风险**:")
                    for ce in theme.counter_evidence:
                        lines.append(f"  - ⚠️ {ce}")
                    lines.append("")
                if theme.counter_evidence_ids:
                    lines.append(f"**反证证据 ID**: {', '.join(theme.counter_evidence_ids)}")
                    lines.append("")
                if theme.limitations:
                    lines.append("**局限性与不确定性**:")
                    for lim in theme.limitations:
                        lines.append(f"  - 📝 {lim}")
                    lines.append("")
                if theme.industry_mapping:
                    lines.extend([
                        "**行业分布**:", "",
                        "| 行业 ID | 权重 |", "|---|---|"])
                    for im in theme.industry_mapping:
                        lines.append(
                            f"| {im.get('industry_id', '?')} "
                            f"| {im.get('weight', 1.0):.2f} |")
                    lines.append("")
                if theme.invalidating_conditions:
                    lines.append("**失效条件**:")
                    for ic in theme.invalidating_conditions:
                        lines.append(f"  - 🚫 {ic}")
                    lines.append("")
                if theme.open_questions:
                    lines.append("**待研究问题**:")
                    for oq in theme.open_questions:
                        lines.append(f"  - ❓ {oq}")
                    lines.append("")
                if theme.related_entity_ids:
                    ids = theme.related_entity_ids
                    suffix = f" ... (+{len(ids) - 10})" if len(ids) > 10 else ""
                    lines.append(
                        f"**关联实体**: {', '.join(ids[:10])}{suffix}")
                    lines.append("")
                # Triggers detail (collapsed)
                lines.extend([
                    "<details>",
                    f"<summary>触发信号详情（{len(theme.triggers)} 个）</summary>",
                    "",
                ])
                for j, t in enumerate(theme.triggers, 1):
                    lines.append(
                        f"**{j}.** `[{t.trigger_type}]` {t.description} "
                        f"(strength={t.strength:.2f})")
                    if t.industry_ids:
                        lines.append(
                            f"  - 行业: {', '.join(t.industry_ids[:5])}")
                    if t.graph_node_ids:
                        lines.append(f"  - 图节点: {len(t.graph_node_ids)} 个")
                    if t.evidence_ids:
                        lines.append(f"  - 证据: {len(t.evidence_ids)} 条")
                lines.extend(["</details>", ""])
        elif result.status in ("insufficient_evidence",):
            lines.extend([
                "## 结果", "",
                "未发现足够证据生成投资主题。建议：",
                "- 扩展 industry_ids 范围",
                "- 增加更多关键词",
                "- 切换 discovery_mode（如 graph_based → keyword_sweep）", "",
            ])

        if result.data_degraded:
            lines.extend([
                "## ⚠️ 数据降级", "",
                "当前发现模式无可用公开 API 接口，流水线已降级。部分数据可能不完整。", "",
            ])

        lines.extend([
            "---",
            f"*报告由 ThemeDiscoveryPipeline 确定性生成 · {now_iso()}*",
        ])
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════
    # 静态辅助方法
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _derive_name(cluster: List[ThemeTrigger], all_inds: List[str]) -> str:
        """从聚类推导主题名称。"""
        parts: List[str] = []
        for ind in all_inds[:2]:
            short = ind.replace("industry:", "").replace("Industry:", "")
            parts.append(short)
        if not parts:
            for t in cluster:
                if t.keyword and t.keyword not in parts:
                    parts.append(t.keyword)
                    if len(parts) >= 2:
                        break
        if not parts:
            parts = [f"{len(cluster)}-信号主题"]
        label = " × ".join(parts[:3])
        return label + " …" if len(all_inds) > 2 else label

    @staticmethod
    def _derive_statement(name: str, n_trig: int, cross_count: int) -> str:
        """确定性生成 theme statement。"""
        if cross_count >= 3:
            return (
                f"{name}：跨 {cross_count} 个行业的关联主题，"
                f"基于 {n_trig} 个触发信号识别，存在结构性传导可能。")
        if cross_count >= 2:
            return (
                f"{name}：涉及 {cross_count} 个行业的交叉主题，"
                f"基于 {n_trig} 个触发信号初步识别。")
        return (
            f"{name}：单一行业关联主题，"
            f"基于 {n_trig} 个触发信号识别，需进一步验证。")

    @staticmethod
    def _cluster_confidence(cluster: List[ThemeTrigger]) -> float:
        """确定性聚类置信度计算。"""
        if not cluster:
            return 0.0
        score = 0.0
        for t in cluster:
            if t.trigger_type == "graph_anomaly":
                score += t.strength * 0.7 + (len(t.graph_node_ids) / 5.0) * 0.3
            elif t.trigger_type == "keyword_sweep":
                score += t.strength * 0.4 + (len(t.evidence_ids) / 5.0) * 0.2
            else:
                score += t.strength * 0.3
        return round(max(0.05, min(score / len(cluster), 0.98)), 2)

    @staticmethod
    def _merge_singletons(themes: List[ThemeHypothesis]) -> List[ThemeHypothesis]:
        """将单 trigger 主题合并到行业重叠的多 trigger 主题。"""
        if len(themes) <= 1:
            return themes
        singletons = [t for t in themes if len(t.triggers) <= 1]
        multi = [t for t in themes if len(t.triggers) > 1]
        if not multi or not singletons:
            return themes

        merged_ids: Set[str] = set()
        for s in singletons:
            s_inds = {im.get("industry_id", "") for im in s.industry_mapping}
            best, best_overlap = None, 0
            for m in multi:
                m_inds = {im.get("industry_id", "") for im in m.industry_mapping}
                ov = len(s_inds & m_inds)
                if ov > best_overlap:
                    best_overlap, best = ov, m
            if best is not None and best_overlap > 0:
                best.triggers.extend(s.triggers)
                exist = {im.get("industry_id", "") for im in best.industry_mapping}
                for im in s.industry_mapping:
                    if im.get("industry_id", "") not in exist:
                        best.industry_mapping.append(im)
                        exist.add(im.get("industry_id", ""))
                best.cross_industry_count = len(exist)
                for eid in s.related_entity_ids:
                    if eid not in best.related_entity_ids:
                        best.related_entity_ids.append(eid)
                for eid in s.supporting_evidence_ids:
                    if eid not in best.supporting_evidence_ids:
                        best.supporting_evidence_ids.append(eid)
                best.confidence = ThemeDiscoveryPipeline._cluster_confidence(
                    best.triggers)
                merged_ids.add(s.hypothesis_id)

        return [t for t in themes if t.hypothesis_id not in merged_ids]
