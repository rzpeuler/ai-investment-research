"""模型路由（Phase 3 任务书 12.3、12.6）。

- Pro 升级条件（业务复杂度路由，满足任一）：
  reasoning_conflict_count>=3 / 独立 S/A 来源对核心事实冲突 /
  supply_chain_hops>3 / top2 原因得分差<8 / Flash 结构化输出连续两次校验失败 /
  直接触发与事后解释标签关键争议 / 多原因候选均>=70 且机制重叠 /
  重大风险事件存在相反证据 / 跨多个行业或概念的复杂传导 / 需要修改核心规则或本体
- 每个任务最多一次 Pro 调用；Pro 后仍无法解决 -> SOURCE_CONFLICT 或
  UNEXPLAINED_MOVE + needs_human_review
- 业务升级（Flash->Pro）与 provider 故障回退（同级模型换端点/供应商）分离，
  不得共用一个 fallback=true 字段掩盖
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.models import ModelRoute


@dataclass
class EscalationVerdict:
    escalate: bool
    reasons: List[str] = field(default_factory=list)


class ModelRouter:
    """Flash/Pro 业务升级路由。"""

    def __init__(self, default_model: str = "deepseek-v4-flash",
                 pro_model: str = "deepseek-v4-pro"):
        self.default_model = default_model
        self.pro_model = pro_model

    # ---------- 升级条件（任务书 12.3） ----------

    def should_escalate(self, ctx: Dict[str, Any]) -> EscalationVerdict:
        reasons: List[str] = []
        if ctx.get("reasoning_conflict_count", 0) >= 3:
            reasons.append("reasoning_conflict_count>=3")
        if ctx.get("high_authority_conflict"):
            reasons.append("独立 S/A 来源对核心事实冲突")
        if ctx.get("supply_chain_hops", 0) > 3:
            reasons.append("supply_chain_hops>3")
        top_gap = ctx.get("top2_score_gap")
        if top_gap is not None and top_gap < 8:
            reasons.append("top2 原因得分差<8")
        if ctx.get("flash_schema_failures", 0) >= 2:
            reasons.append("Flash 结构化输出连续两次校验失败")
        if ctx.get("direct_trigger_dispute"):
            reasons.append("直接触发与事后解释标签存在关键争议")
        if ctx.get("multi_cause_overlap"):
            reasons.append("多原因候选均>=70 且机制重叠")
        if ctx.get("major_risk_contradiction"):
            reasons.append("重大风险事件存在相反证据")
        if ctx.get("cross_industry_complex"):
            reasons.append("跨多个行业或概念的复杂传导")
        if ctx.get("core_rule_change"):
            reasons.append("需要修改核心规则或本体")
        return EscalationVerdict(escalate=bool(reasons), reasons=reasons)

    # ---------- 路由记录 ----------

    def build_route(
        self,
        llm_called: bool,
        selected_model: Optional[str] = None,
        failure_stage: Optional[str] = None,
        limitation: str = "semantic_llm_modules_not_connected",
        escalation_reasons: Optional[List[str]] = None,
        business_escalation_reason: Optional[str] = None,
        provider_fallback_used: bool = False,
        provider_fallback_reason: Optional[str] = None,
    ) -> ModelRoute:
        """构造 ModelRoute（如实记录；业务升级与 provider 故障回退分离）。"""
        # 已调用但失败（failure_stage 非空）-> deterministic_fallback + llm_called=true（任务书 12.5）
        mode = "llm" if (llm_called and failure_stage is None) else "deterministic_fallback"
        return ModelRoute(
            mode=mode,  # type: ignore[arg-type]
            llm_called=llm_called,
            intended_default_model=self.default_model,
            selected_model=selected_model,
            failure_stage=failure_stage,
            limitation=limitation,
            escalated=bool(escalation_reasons),
            escalation_reasons=escalation_reasons or [],
            business_escalation_reason=business_escalation_reason,
            provider_fallback_used=provider_fallback_used,
            provider_fallback_reason=provider_fallback_reason,
        )
