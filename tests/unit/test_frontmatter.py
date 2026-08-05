"""Front Matter 校验器测试：正常、缺失字段失败、坏 YAML 失败。"""
from __future__ import annotations

import pytest

from research_os.reports.frontmatter import (
    FRONTMATTER_REQUIRED_FIELDS,
    parse_frontmatter,
    validate_frontmatter,
    validate_frontmatter_file,
)


def build_report(frontmatter: dict, body: str = "# 测试报告\n内容\n") -> str:
    import yaml

    fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
    return f"---\n{fm}---\n{body}"


def full_frontmatter(**overrides) -> dict:
    data = {
        "report_id": "rep-001",
        "scenario": "morning_brief",
        "title": "A股每日晨报 2026-08-05",
        "created_at": "2026-08-05T08:10:00",
        "as_of": "2026-08-05T08:00:00",
        "timezone": "Asia/Shanghai",
        "entities": [],
        "time_window": {"start": "2026-08-04T20:00:00", "end": "2026-08-05T08:00:00"},
        "data_status": "ok",
        "source_coverage": {"sources": 0},
        "model_route": "flash_default",
        "runtime_seconds": 120,
        "validator_status": "pending",
        "knowledge_coordinates": [],
    }
    data.update(overrides)
    return data


def test_full_frontmatter_passes():
    result = validate_frontmatter(build_report(full_frontmatter()))
    assert result.ok, result.errors
    assert result.frontmatter is not None


def test_missing_each_required_field_fails():
    for field in FRONTMATTER_REQUIRED_FIELDS:
        fm = full_frontmatter()
        del fm[field]
        result = validate_frontmatter(build_report(fm))
        assert not result.ok
        assert any(f"缺少必需字段: {field}" in e for e in result.errors)


def test_no_frontmatter_fails():
    result = validate_frontmatter("# 没有 Front Matter 的报告\n")
    assert not result.ok
    assert any("缺少 Front Matter" in e for e in result.errors)


def test_bad_yaml_fails():
    result = validate_frontmatter("---\nreport_id: [unclosed\n---\nbody\n")
    assert not result.ok


def test_wrong_timezone_fails():
    result = validate_frontmatter(build_report(full_frontmatter(timezone="UTC")))
    assert not result.ok
    assert any("timezone" in e for e in result.errors)


def test_invalid_datetime_fails():
    result = validate_frontmatter(build_report(full_frontmatter(created_at="yesterday")))
    assert not result.ok


def test_invalid_runtime_seconds_fails():
    result = validate_frontmatter(build_report(full_frontmatter(runtime_seconds="fast")))
    assert not result.ok


def test_parse_extracts_body():
    fm, body = parse_frontmatter(build_report(full_frontmatter(), body="# 正文\n"))
    assert fm["report_id"] == "rep-001"
    assert body.startswith("# 正文")


def test_file_missing_fails(tmp_path):
    result = validate_frontmatter_file(tmp_path / "nope.md")
    assert not result.ok
    assert any("文件不存在" in e for e in result.errors)


def test_file_valid_passes(tmp_path):
    p = tmp_path / "report.md"
    p.write_text(build_report(full_frontmatter()), encoding="utf-8")
    result = validate_frontmatter_file(p)
    assert result.ok, result.errors


def test_validation_flag_consistency():
    """ok 标志与 errors 列表一致性（正常/失败两个方向）。"""
    assert validate_frontmatter(build_report(full_frontmatter())).ok is True
    assert validate_frontmatter("# 无 Front Matter").ok is False
