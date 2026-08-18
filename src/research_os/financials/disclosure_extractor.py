"""P7-D4：确定性财务三表提取器（FinancialStatementExtractor）。

输入：DocumentRecord + DocumentBlock[]（唯一输入；禁止直接读 PDF/URL/LLM）。
输出：FinancialReport / FinancialFact candidates + rejected rows + warnings。

规则（taskbook P7-D4 §27-35、§62）：
- 只接受 CORE_FINANCIAL_CODES（9 码）；只接受 consolidated；只接受 audited annual report。
- FinancialTaxonomy.lookup() 精确匹配才可自动接受；fuzzy_lookup 只产生 warning。
- current-period 列必须可证明（列标题 authority）；无法证明 → reject 该行。
- currency/unit 必须可证明；无法证明 → reject。
- 数值一律 Decimal 字符串（normalize_decimal_string）；禁止 float。
- 任何不确定 → reject 并记录诊断，绝不猜测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from research_os.financials.evidence_binding import CORE_FINANCIAL_CODES
from research_os.financials.taxonomy import FinancialTaxonomy
from research_os.models import DocumentBlock, FinancialFact, FinancialReport
from research_os.utils.decimal import normalize_decimal_string
from research_os.utils.time import now_iso

# ---------- 数值/单位 ----------

_NUMBER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)(?![A-Za-z0-9])"
)
_SPACE_COMPACT = re.compile(r"\s+")

# 单位词 → unit_scale（1 = 元）
_UNIT_SCALES = {
    "元": 1, "人民币元": 1, "千元": 10**3, "万元": 10**4,
    "百万元": 10**6, "百万": 10**6, "亿元": 10**8,
}

# 资产负债表列 authority（current 在前、prior 在后为常见惯例，但以标题为准）
_BS_CURRENT_HEADS = ("期末余额", "期末数", "年末余额", "本期末")
_BS_PRIOR_HEADS = ("期初余额", "期初数", "年初余额", "上期末")
_IS_CURRENT_HEADS = ("本期金额", "本年金额", "本期发生额", "本年累计", "本期")
_IS_PRIOR_HEADS = ("上期金额", "上年金额", "上期发生额", "上年同期", "上期")

_SECTION_CONSOLIDATED = ("合并资产负债表", "合并利润表", "合并现金流量表")
_SECTION_PARENT = ("母公司资产负债表", "母公司利润表", "母公司现金流量表")

_STATEMENT_TYPE_BY_SECTION = {
    "资产负债表": "balance_sheet",
    "利润表": "income_statement",
    "现金流量表": "cash_flow",
}

_INSTANT_BY_STATEMENT = {
    "balance_sheet": "instant",
    "income_statement": "duration",
    "cash_flow": "duration",
}

_INSTANT_CODES = frozenset({"total_assets", "total_liabilities", "equity_attr"})


@dataclass
class RejectedRow:
    """无法自动接受的候选行（诊断用途，不持久化）。"""

    label: str
    taxonomy_code: Optional[str]
    statement_type: str
    reason: str
    raw_text: str


@dataclass
class FinancialExtractionResult:
    report: Optional[FinancialReport]
    facts: List[FinancialFact] = field(default_factory=list)
    rejected_rows: List[RejectedRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unit_scale: Optional[int] = None
    currency: str = "CNY"


def _compact(text: str) -> str:
    return _SPACE_COMPACT.sub("", text or "")


def _extract_numbers(text: str) -> List[str]:
    """提取文本中全部数值 token（保留负号/小数点/千分位）。"""
    return [m.group(1) for m in _NUMBER_TOKEN.finditer(text)]


def _resolve_unit_scale(blocks: Sequence[DocumentBlock]) -> Optional[int]:
    """从文档上下文证明单位；无法证明返回 None（reject）。"""
    for block in blocks:
        text = _compact(block.content_excerpt or "")
        for unit_word, scale in _UNIT_SCALES.items():
            if unit_word in text and "单位" in text:
                return scale
    # 常见年报第一页/封面单位声明（宽松但须出现"单位"字样）
    return None


def _current_column_index(header_text: str, is_balance_sheet: bool) -> Optional[int]:
    """从表头行证明 current-period 列索引（0-based）；无法证明返回 None。

    表头文本形如：“项目 期末余额 期初余额”（资产负债表）或“项目 本期金额 上期金额”。
    若 current 列标题出现且先于 prior 标题，返回其索引；歧义/缺失 → None。
    """
    heads = _BS_CURRENT_HEADS if is_balance_sheet else _IS_CURRENT_HEADS
    priors = _BS_PRIOR_HEADS if is_balance_sheet else _IS_PRIOR_HEADS
    tokens = _SPACE_COMPACT.sub(" ", header_text or "").split()
    current_idx = None
    for i, tok in enumerate(tokens):
        compact_tok = _compact(tok)
        if compact_tok in {_compact(h) for h in heads}:
            current_idx = i
            break
    if current_idx is None:
        return None
    # prior 列必须存在且位于 current 之后，否则列语义不完整
    prior_after = any(
        _compact(tok) in {_compact(p) for p in priors}
        for tok in tokens[current_idx + 1:]
    )
    if not prior_after:
        return None
    return current_idx


def _classify_section(section_title: str) -> Tuple[Optional[str], Optional[str]]:
    """返回 (statement_type, scope)；无法确定 → (None, None)。"""
    compact = _compact(section_title)
    stmt = None
    for key, stmt_type in _STATEMENT_TYPE_BY_SECTION.items():
        if _compact(key) in compact:
            stmt = stmt_type
            break
    if stmt is None:
        return None, None
    if any(_compact(s) in compact for s in _SECTION_CONSOLIDATED):
        return stmt, "consolidated"
    if any(_compact(s) in compact for s in _SECTION_PARENT):
        return stmt, "parent"
    return stmt, None  # 无法判断合并/母公司 → reject


def _is_table_authority(block: DocumentBlock) -> bool:
    """判定 block 是否属于三表 section 内容（页级粗判：block 邻近三表标题）。"""
    return block.block_type in ("text", "table")


class FinancialStatementExtractor:
    """确定性三表提取器：DocumentBlock[] → FinancialReport/FinancialFact candidates。"""

    def __init__(self, taxonomy: Optional[FinancialTaxonomy] = None):
        self._taxonomy = taxonomy or FinancialTaxonomy()

    def extract(
        self,
        record: FinancialReport | None,
        blocks: Sequence[DocumentBlock],
        *,
        document: object | None = None,
        company_entity_id: str,
        fiscal_year: int,
        period_end: str,
        period_start: str,
        published_at: str,
    ) -> FinancialExtractionResult:
        """从 DocumentBlock 提取财务事实候选。

        record：可复用的 FinancialReport 骨架（company/period 已定）；None 时仅产出事实。
        document：DocumentRecord（用于 source_document_id/source_block_ids）。
        """
        created_at = now_iso()
        result = FinancialExtractionResult(report=None)
        unit_scale = _resolve_unit_scale(blocks)
        result.unit_scale = unit_scale
        if unit_scale is None:
            result.warnings.append("无法证明报告单位 → 全部行 reject")
            return result

        # 1) 定位三表 section 边界（页序线性扫描，文本 authority）
        sections: List[Tuple[str, int, int]] = []  # (title, start_idx, end_idx)
        lines = [block.content_excerpt or "" for block in blocks]
        for i, line in enumerate(lines):
            for marker in _SECTION_CONSOLIDATED:
                if _compact(marker) in _compact(line):
                    sections.append((marker, i, len(lines)))
                    break
        if not sections:
            result.warnings.append("未找到合并三表 section 标题 → 无 accepted facts")
            return result

        # 2) 对每个 section 逐行解析
        for title, start, end in sections:
            stmt_type, scope = _classify_section(title)
            if stmt_type is None or scope != "consolidated":
                result.warnings.append(f"{title}: 无法证明 consolidated scope → skip")
                continue
            is_bs = stmt_type == "balance_sheet"
            self._extract_section(
                result=result, blocks=blocks[start:end], title=title,
                stmt_type=stmt_type, is_bs=is_bs, unit_scale=unit_scale,
                company_entity_id=company_entity_id, fiscal_year=fiscal_year,
                period_end=period_end, period_start=period_start,
                published_at=published_at, created_at=created_at, document=document,
            )
        return result

    def _extract_section(
        self,
        *,
        result: FinancialExtractionResult,
        blocks: Sequence[DocumentBlock],
        title: str,
        stmt_type: str,
        is_bs: bool,
        unit_scale: int,
        company_entity_id: str,
        fiscal_year: int,
        period_end: str,
        period_start: str,
        published_at: str,
        created_at: str,
        document: object | None,
    ) -> None:
        doc_id = getattr(document, "document_id", None) if document else None
        # 表头列 authority：在 section 前部找含 current/prior 列标题的行
        current_col = None
        header_line: Optional[str] = None
        for block in blocks:
            text = _SPACE_COMPACT.sub(" ", block.content_excerpt or "")
            idx = _current_column_index(text, is_bs)
            if idx is not None:
                current_col = idx
                header_line = text
                break
        if current_col is None:
            result.rejected_rows.append(RejectedRow(
                label="(section)", taxonomy_code=None, statement_type=stmt_type,
                reason="current-period 列无法证明（缺列标题 authority）", raw_text=title,
            ))
            return
        # 数字位置 = 表头列索引 - 1（表头首列为科目列；附注等中间列会导致恒等式校验失败而 reject）
        current_number_index = current_col - 1
        if current_number_index < 0:
            result.rejected_rows.append(RejectedRow(
                label="(section)", taxonomy_code=None, statement_type=stmt_type,
                reason="列标题 authority 异常（current 列在科目列之前）", raw_text=title,
            ))
            return

        section_facts: List[FinancialFact] = []
        for block in blocks:
            text = block.content_excerpt or ""
            compact = _compact(text)
            # 跳过表头/标题/纯数字行
            if _current_column_index(_SPACE_COMPACT.sub(" ", text), is_bs) is not None:
                continue
            numbers = _extract_numbers(text)
            if not numbers:
                continue
            # 去掉数字后的标签（科目名）
            label = _NUMBER_TOKEN.sub("", compact).strip("：:、,， ")
            if not label or len(label) > 60:
                continue
            code = self._taxonomy.lookup(label)
            if code is None:
                fuzzy = self._taxonomy.fuzzy_lookup(label)
                if fuzzy is not None:
                    result.rejected_rows.append(RejectedRow(
                        label=label, taxonomy_code=fuzzy, statement_type=stmt_type,
                        reason=f"仅 fuzzy 匹配（{fuzzy}）→ 不得自动接受", raw_text=text[:120],
                    ))
                continue
            if code not in CORE_FINANCIAL_CODES:
                continue
            # current 列取值：行内数字序列的 current_number_index 位置
            if current_number_index >= len(numbers):
                result.rejected_rows.append(RejectedRow(
                    label=label, taxonomy_code=code, statement_type=stmt_type,
                    reason=f"行数字列数不足（current_idx={current_number_index}, nums={len(numbers)}）",
                    raw_text=text[:120],
                ))
                continue
            raw = numbers[current_number_index]
            raw_clean = raw.replace(",", "")  # 千分位是确定性展示分隔符
            try:
                normalized = normalize_decimal_string(raw_clean)
            except ValueError:
                result.rejected_rows.append(RejectedRow(
                    label=label, taxonomy_code=code, statement_type=stmt_type,
                    reason=f"非法数值: {raw}", raw_text=text[:120],
                ))
                continue
            if stmt_type == "balance_sheet" and code not in _INSTANT_CODES:
                continue
            section_facts.append(FinancialFact(
                fact_id="",  # 由持久化层 UUID5 生成（幂等）
                fact_key=code,
                financial_report_id="",  # 持久化层回填
                company_entity_id=company_entity_id,
                statement_type=stmt_type,
                taxonomy_code=code,
                label_raw=label,
                period_start=period_start if stmt_type != "balance_sheet" else None,
                period_end=period_end,
                instant_or_duration=(
                    "instant" if code in _INSTANT_CODES else
                    _INSTANT_BY_STATEMENT.get(stmt_type, "duration")
                ),
                statement_scope="consolidated",
                currency="CNY",
                unit_scale=unit_scale,
                raw_value=raw_clean,
                normalized_value=normalized,
                normalized_unit="CNY",
                value_status="reported",
                source_document_id=doc_id,
                source_block_ids=[block.block_id] if block.block_id else [],
                evidence_ids=[],
                source_priority=1,
                valid_from=published_at,
                created_at=created_at,
            ))
        # 资产负债表恒等式交叉校验（current-period 列选择的确定性证明）
        if is_bs and section_facts:
            assets = next(
                (f for f in section_facts if f.taxonomy_code == "total_assets"), None)
            liab = next(
                (f for f in section_facts if f.taxonomy_code == "total_liabilities"), None)
            equity = next(
                (f for f in section_facts if f.taxonomy_code == "equity_attr"), None)
            if assets is not None and liab is not None and equity is not None:
                try:
                    a = float(assets.normalized_value or 0)
                    b = float(liab.normalized_value or 0) + float(equity.normalized_value or 0)
                    if abs(a - b) / max(abs(a), abs(b), 1.0) > 1e-6:
                        result.rejected_rows.append(RejectedRow(
                            label="(balance_sheet)", taxonomy_code=None,
                            statement_type="balance_sheet",
                            reason=(
                                f"资产负债表恒等式不成立（assets={a}, liab+equity={b}）"
                                f" → current-period 列选择不可信"
                            ),
                            raw_text=title,
                        ))
                        section_facts = []  # 整表 reject，禁止猜测列
                        result.warnings.append(
                            f"{title}: 资产负债表恒等式校验失败 → 该表全部行 reject")
                except (TypeError, ValueError):
                    section_facts = []
        result.facts.extend(section_facts)
