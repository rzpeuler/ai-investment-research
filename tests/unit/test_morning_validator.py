"""晨报验证器测试（Phase 2 任务 22 节）。

Front Matter 日期关系 / 覆盖说明 / 证据 / 禁止词 / 内容质量。
"""
from __future__ import annotations

from research_os.reports import validate_report
from research_os.reports.validator import validate_morning_brief


def _fm(**ov) -> dict:
    d = {
        "report_id": "r1", "scenario": "morning_brief", "title": "晨报",
        "created_at": "2026-08-06T08:10:00", "as_of": "2026-08-06T08:00:00",
        "timezone": "Asia/Shanghai", "entities": [],
        "time_window": {"start": "2026-08-05T20:00:00", "end": "2026-08-06T08:00:00"},
        "window_start": "2026-08-05T20:00:00", "window_end": "2026-08-06T08:00:00",
        "scheduled_for": "2026-08-06T08:10:00",
        "actual_started_at": "2026-08-06T08:12:00",
        "actual_finished_at": "2026-08-06T08:15:00",
        "delayed": False, "delay_seconds": 0,
        "data_status": "ok", "source_coverage": {},
        "model_route": "flash_default", "runtime_seconds": 60,
        "validator_status": "pending", "knowledge_coordinates": [],
    }
    d.update(ov)
    return d


def _build(fm: dict, body: str) -> str:
    import yaml

    fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
    return f"---\n{fm_yaml}---\n{body}"


def _good_body() -> str:
    return """# A股每日晨报 2026-08-06

## 执行说明
- 信息窗口：2026-08-05T20:00:00 至 2026-08-06T08:00:00
- 实际生成时间：2026-08-06T08:15:00
- 数据覆盖状态：正常

## 一、重大必读
### 贵州茅台发布半年报
- **分数：**80（重大必读）
- **分类：**company/announcement
- **摘要：**营收同比增长

## 六、四个监测方向覆盖
### 7×24快讯
- 覆盖状态：covered
- 使用来源：cls
- 是否仅人工输入：否
- 数据限制：无
### 社区舆情
- 覆盖状态：manual_only
- 使用来源：无
- 是否仅人工输入：是
- 数据限制：当前仅支持 manual_inbox

## 七、隔夜外围总结
隔夜市场结构化行情数据当前未完成可靠数据源接入。

## 八、今日待验证事项
- 待官方披露确认

## 九、未纳入正文的重要候选
- 无

## 十、数据与来源说明
- 实际成功来源：cls
"""


def test_valid_morning_report_passes(tmp_path):
    p = tmp_path / "m.md"
    p.write_text(_build(_fm(), _good_body()), encoding="utf-8")
    result = validate_report(p)
    assert result.ok, result.errors


def test_missing_window_fields_fails(tmp_path):
    fm = _fm()
    del fm["window_start"]
    p = tmp_path / "m.md"
    p.write_text(_build(fm, _good_body()), encoding="utf-8")
    result = validate_report(p)
    assert not result.ok
    assert any("window_start" in e for e in result.errors)


def test_window_order_inverted_fails(tmp_path):
    fm = _fm(window_start="2026-08-06T08:00:00", window_end="2026-08-05T20:00:00")
    p = tmp_path / "m.md"
    p.write_text(_build(fm, _good_body()), encoding="utf-8")
    result = validate_report(p)
    assert not result.ok
    assert any("window_start 必须早于" in e for e in result.errors)


def test_as_of_before_window_end_fails(tmp_path):
    fm = _fm(as_of="2026-08-05T21:00:00")
    p = tmp_path / "m.md"
    p.write_text(_build(fm, _good_body()), encoding="utf-8")
    result = validate_report(p)
    assert not result.ok
    assert any("as_of 不得早于窗口结束" in e for e in result.errors)


def test_delayed_requires_delay_info(tmp_path):
    fm = _fm(delayed=True, delay_seconds=0)
    p = tmp_path / "m.md"
    p.write_text(_build(fm, _good_body()), encoding="utf-8")
    result = validate_report(p)
    assert not result.ok
    assert any("delay_seconds" in e for e in result.errors)


def test_relative_date_in_item_rejected(tmp_path):
    body = _good_body().replace(
        "- **时间：**", "- **时间：**今天") if "- **时间：**" in _good_body() else _good_body()
    body = body.replace("### 贵州茅台发布半年报\n", "### 贵州茅台发布半年报\n- **时间：**今天\n")
    p = tmp_path / "m.md"
    p.write_text(_build(_fm(), body), encoding="utf-8")
    errors, _ = validate_morning_brief(body, _fm())
    assert any("模糊日期" in e for e in errors)


def test_degraded_without_missing_data_fails(tmp_path):
    """声明 degraded 但报告无缺失/降级说明 -> 失败。"""
    fm = _fm(data_status="degraded")
    # body 保持"数据覆盖状态：正常"，未披露任何缺失 -> 应失败
    p = tmp_path / "m.md"
    p.write_text(_build(fm, _good_body()), encoding="utf-8")
    result = validate_report(p)
    assert not result.ok
    assert any("降级" in e for e in result.errors)


def test_uncovered_written_as_no_info_fails():
    """未覆盖方向不得写成'无信息'；且覆盖块必须有状态标注。"""
    body = _good_body() + """### 机构动向
机构方向没有信息，本期无内容。

## 附录
"""
    errors, _ = validate_morning_brief(body, _fm())
    assert errors, "未覆盖方向写成'无信息'必须被拦截"
    assert any("无信息" in e or "覆盖状态" in e for e in errors)


def test_forbidden_words_morning(tmp_path):
    """晨报禁止项：明日操作/建议买入 等。"""
    for word in ("明日操作", "建议买入", "跟随操作"):
        body = _good_body() + f"\n当前给出{word}建议。\n"
        p = tmp_path / f"m_{word}.md"
        p.write_text(_build(_fm(), body), encoding="utf-8")
        result = validate_report(p)
        assert not result.ok, f"{word} 未被拦截"


def test_normative_words_not_misflagged(tmp_path):
    """避免误伤：引文中的正常词语。"""
    body = _good_body() + "\n该公司公告中提及'买入期权'一词（引文）。\n"
    p = tmp_path / "m.md"
    p.write_text(_build(_fm(), body), encoding="utf-8")
    result = validate_report(p)
    assert result.ok, result.errors


def test_empty_section_warns():
    """空章节产生告警（内容质量）。"""
    body = _good_body() + "\n### 一个空小节\n\n\n"
    _, warnings = validate_morning_brief(body, _fm())
    assert any("空章节" in w for w in warnings)
