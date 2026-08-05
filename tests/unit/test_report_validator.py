"""基础报告校验器测试：禁止输出项检测（目标价/买卖建议/引导性语言）。"""
from __future__ import annotations

from research_os.reports import FORBIDDEN_WORDS, validate_report


def _report_with_fm(body: str) -> str:
    fm = (
        "---\n"
        "report_id: rep-002\n"
        "scenario: stock_research_report\n"
        "title: 测试\n"
        "created_at: 2026-08-05T08:10:00\n"
        "as_of: 2026-08-05T08:00:00\n"
        "timezone: Asia/Shanghai\n"
        "entities: []\n"
        "time_window: {start: null, end: null}\n"
        "data_status: ok\n"
        "source_coverage: {}\n"
        "model_route: flash_default\n"
        "runtime_seconds: 1\n"
        "validator_status: pending\n"
        "knowledge_coordinates: []\n"
        "---\n"
    )
    return fm + body


def test_clean_report_passes(tmp_path):
    p = tmp_path / "ok.md"
    p.write_text(_report_with_fm("# 报告\n公司业务稳健。\n"), encoding="utf-8")
    result = validate_report(p)
    assert result.ok, result.errors


def test_target_price_fails(tmp_path):
    p = tmp_path / "tp.md"
    p.write_text(_report_with_fm("我们给出目标价 1200 元。\n"), encoding="utf-8")
    result = validate_report(p)
    assert not result.ok
    assert any("目标价" in e for e in result.errors)


def test_buy_language_fails(tmp_path):
    p = tmp_path / "buy.md"
    p.write_text(_report_with_fm("当前价位可以买。\n"), encoding="utf-8")
    result = validate_report(p)
    assert not result.ok


def test_all_forbidden_words_are_detected(tmp_path):
    """每个禁止词单独触发失败。"""
    for word in FORBIDDEN_WORDS:
        p = tmp_path / f"w_{word}.md"
        p.write_text(_report_with_fm(f"报告提到：{word}。\n"), encoding="utf-8")
        result = validate_report(p)
        assert not result.ok, f"禁止词 {word} 未被检测到"


def test_missing_file_fails(tmp_path):
    result = validate_report(tmp_path / "nope.md")
    assert not result.ok


def test_missing_frontmatter_fails(tmp_path):
    p = tmp_path / "no_fm.md"
    p.write_text("# 无 Front Matter\n", encoding="utf-8")
    result = validate_report(p)
    assert not result.ok
