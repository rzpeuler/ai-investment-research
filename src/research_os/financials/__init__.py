"""财务数据模块（Phase 4 Commit 3 起）。"""
from research_os.financials.evidence_binding import (
    CORE_FINANCIAL_CODES,
    FinancialBindingResult,
    bind_official_financial_evidence,
    load_binding_manifest,
)

__all__ = [
    "CORE_FINANCIAL_CODES",
    "FinancialBindingResult",
    "bind_official_financial_evidence",
    "load_binding_manifest",
]
