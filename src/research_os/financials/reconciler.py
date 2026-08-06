"""三表勾稽验证（Phase 4 任务书 3.11/Commit 7）。

- 资产负债恒等：Assets = Liabilities + Equity，容差 max(absolute, |Assets|*relative)；
- 现金流勾稽：EndingCash = BeginningCash + NetIncrease + FXEffect + Other；
  缺少披露项只输出 partial_reconciliation，不认定报表错误。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

DEFAULT_ABS_TOLERANCE = Decimal("0.01")
DEFAULT_REL_TOLERANCE = Decimal("0.0001")


def _dec(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


@dataclass
class ReconciliationIssue:
    code: str  # balance_sheet_identity / cash_flow_partial / cash_flow_mismatch
    severity: str  # error / warning / info
    message: str
    actual: Optional[str] = None
    expected: Optional[str] = None


@dataclass
class ReconciliationResult:
    ok: bool
    issues: List[ReconciliationIssue] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def reconcile_balance_sheet(
    total_assets: Optional[str],
    total_liabilities: Optional[str],
    total_equity: Optional[str],
    abs_tolerance: Decimal = DEFAULT_ABS_TOLERANCE,
    rel_tolerance: Decimal = DEFAULT_REL_TOLERANCE,
) -> ReconciliationResult:
    """资产负债恒等：Assets − Liabilities − Equity 在容差内。"""
    da, dl, de = _dec(total_assets), _dec(total_liabilities), _dec(total_equity)
    if da is None or dl is None or de is None:
        return ReconciliationResult(
            ok=False,
            issues=[ReconciliationIssue(
                code="balance_sheet_identity", severity="warning",
                message="三表数据不全，无法勾稽（不认定报表错误）",
            )],
        )
    diff = da - dl - de
    tolerance = max(abs_tolerance, abs(da) * rel_tolerance)
    if abs(diff) <= tolerance:
        return ReconciliationResult(ok=True, notes=[f"恒等在容差内（差 {diff}，容差 {tolerance}）"])
    return ReconciliationResult(
        ok=False,
        issues=[ReconciliationIssue(
            code="balance_sheet_identity", severity="error",
            message=f"资产负债不恒等：差 {diff} 超出容差 {tolerance}",
            actual=str(diff), expected="0",
        )],
    )


def reconcile_cash_flow(
    ending_cash: Optional[str],
    beginning_cash: Optional[str],
    net_increase: Optional[str],
    fx_effect: Optional[str] = None,
    other_items: Optional[str] = None,
) -> ReconciliationResult:
    """现金流勾稽：EndingCash = BeginningCash + NetIncrease + FXEffect + Other。

    缺披露项时输出 partial_reconciliation（warning），不认定报表错误。
    """
    d_end, d_begin, d_net = _dec(ending_cash), _dec(beginning_cash), _dec(net_increase)
    if d_end is None or d_begin is None or d_net is None:
        return ReconciliationResult(
            ok=False,
            issues=[ReconciliationIssue(
                code="cash_flow_partial", severity="warning",
                message="现金流勾稽输入不全，输出 partial_reconciliation",
            )],
        )
    d_fx = _dec(fx_effect) or Decimal(0)
    d_other = _dec(other_items) or Decimal(0)
    expected = d_begin + d_net + d_fx + d_other
    if d_end == expected:
        return ReconciliationResult(ok=True, notes=["现金流勾稽一致"])
    diff = d_end - expected
    tolerance = max(DEFAULT_ABS_TOLERANCE, abs(d_end) * DEFAULT_REL_TOLERANCE)
    if abs(diff) <= tolerance:
        return ReconciliationResult(ok=True, notes=[f"现金流勾稽在容差内（差 {diff}）"])
    return ReconciliationResult(
        ok=False,
        issues=[ReconciliationIssue(
            code="cash_flow_mismatch", severity="warning",
            message=f"现金流勾稽不一致：差 {diff}（缺披露项时可能为 partial，不认定报表错误）",
            actual=str(d_end), expected=str(expected),
        )],
    )
