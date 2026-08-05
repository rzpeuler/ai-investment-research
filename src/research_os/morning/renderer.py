"""晨报 Markdown 渲染（Phase 2 任务 18 节模板）。

结构化数据中必须包含完整字段（分类/监测方向/信息性质/时间/主体/摘要/
重要性/影响路径/确定性/待验证/证据）；正文可适度压缩。
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List

from research_os.morning.pipeline import PipelineArtifacts
from research_os.utils.time import now_iso

_SECTION_LABELS = {
    ("macro", "policy"): "政策",
    ("macro", "liquidity"): "流动性",
    ("macro", "economic_data"): "经济数据",
    ("macro", "geopolitics"): "地缘政治",
    ("macro", "emergency"): "突发事件",
    ("industry", "event"): "行业事件",
    ("industry", "trend"): "行业趋势",
    ("industry", "data"): "行业数据",
    ("industry", "policy"): "行业政策",
    ("industry", "technology_breakthrough"): "技术突破",
    ("market", "a_share"): "A股相关市场信息",
    ("market", "hong_kong"): "港股",
    ("market", "us_market"): "美股",
    ("market", "commodity"): "商品",
    ("market", "rates"): "利率",
    ("market", "foreign_exchange"): "汇率",
    ("company", "announcement"): "公告",
    ("company", "operation"): "经营动态",
    ("company", "interaction_and_research"): "互动与调研",
    ("company", "financing"): "融资",
    ("company", "risk"): "风险事件",
}

_OVERNIGHT_DEGRADED = (
    "隔夜市场结构化行情数据当前未完成可靠数据源接入，本期不提供指数涨跌汇总。"
    "（不得以模型记忆或搜索摘要补数字）"
)


def _frontmatter(artifacts: PipelineArtifacts, report_date: date,
                 window_start: str, window_end: str, as_of: str,
                 scheduled_for: str, started_at: str, finished_at: str,
                 delayed: bool, delay_seconds: int) -> List[str]:
    status = "partial" if artifacts.missing_data else "ok"
    lines = [
        "---",
        f"report_id: {artifacts.task_id}",
        "scenario: morning_brief",
        f"title: A股每日晨报 {report_date.isoformat()}",
        f"created_at: {finished_at}",
        f"as_of: {as_of}",
        "timezone: Asia/Shanghai",
        "entities: []",
        f"time_window: {{start: {window_start}, end: {window_end}}}",
        f"window_start: {window_start}",
        f"window_end: {window_end}",
        f"scheduled_for: {scheduled_for}",
        f"actual_started_at: {started_at}",
        f"actual_finished_at: {finished_at}",
        f"delayed: {str(delayed).lower()}",
        f"delay_seconds: {delay_seconds}",
        f"data_status: {status}",
        "source_coverage: {}",
        # 诚实记录模型路由：Phase 2 未接入 LLM，语义环节为确定性规则回退
        "model_route:",
        "  mode: deterministic_fallback",
        "  llm_called: false",
        "  intended_default_model: deepseek-v4-flash",
        "  limitation: semantic_llm_modules_not_connected",
        f"runtime_seconds: 0",
        "validator_status: pending",
        "knowledge_coordinates: []",
        "---",
    ]
    return lines


def _item_block(cid: str, title: str, path: List[str], channel: str,
                ctype: str, published: str, entities: List[str],
                summary: str, importance: str, impact: str,
                certainty: str, verify: List[str], evidence: List[str]) -> List[str]:
    lines = [f"### {title}", ""]
    lines.append(f"- **分类：**{'/'.join(path) or 'unknown'}")
    lines.append(f"- **监测方向：**{channel}")
    lines.append(f"- **信息性质：**{ctype}")
    lines.append(f"- **时间：**{published}")
    lines.append(f"- **涉及主体：**{', '.join(entities) or '待确认'}")
    lines.append(f"- **事件摘要：**{summary or title}")
    lines.append(f"- **重要性：**{importance}")
    lines.append(f"- **影响路径：**{impact}")
    lines.append(f"- **确定性：**{certainty}")
    lines.append(f"- **待验证事项：**{'; '.join(verify) or '待后续验证'}")
    lines.append(f"- **证据：**{', '.join(evidence) or '待补充'}")
    lines.append("")
    return lines


def _cluster_blocks(artifacts: PipelineArtifacts,
                    scores: Dict[str, dict]) -> Dict[str, List[str]]:
    """簇 -> 按分类章节分组的渲染块。"""
    sections: Dict[str, List[str]] = {}
    # candidate_id -> (cluster_id, 相关分数)
    cand_cluster: Dict[str, str] = {}
    for cl in artifacts.clusters:
        for mid in cl.member_candidate_ids:
            cand_cluster[mid] = cl.cluster_id
    cand_score = {s["candidate_id"]: s for s in artifacts.scores}

    for c in artifacts.candidates:
        score = cand_score.get(c.candidate_id)
        if score is None:
            continue
        selected = score["final_score"] >= 65 or score["forced_include"]
        if not selected:
            continue
        path = c.classification_path or ["unknown"]
        key = tuple(path[:2]) if len(path) > 1 else (path[0], "")
        label = _SECTION_LABELS.get(key, "其他")
        cl = next((x for x in artifacts.clusters if x.cluster_id == cand_cluster.get(c.candidate_id)), None)
        conflicts = cl.conflicts if cl else []
        verify = ["核查官方披露" if c.monitoring_channel == "fast_news" else "跟踪后续进展"]
        verify += [f"冲突: {x}" for x in conflicts[:2]]
        importance = band_label(score["final_score"])
        blocks = _item_block(
            cid=c.candidate_id, title=c.title, path=path, channel=c.monitoring_channel,
            ctype=c.content_type, published=c.published_at, entities=c.entities,
            summary=c.summary, importance=importance, impact=importance,
            certainty=f"{score['final_score']:.0f}分（确定性维度 {score['certainty']}/5）",
            verify=verify,
            evidence=[a["claim_id"] for a in artifacts.claims
                      if a.get("object", {}).get("candidate_id") == c.candidate_id],
        )
        sections.setdefault(f"{label}###{cand_cluster.get(c.candidate_id, '')}", []).extend(blocks)
    return sections


def band_label(score: float) -> str:
    if score >= 75:
        return "重大必读"
    if score >= 65:
        return "晨报正文"
    return "候选观察"


def render_morning_brief(
    artifacts: PipelineArtifacts,
    report_date: date,
    window_start: str,
    window_end: str,
    as_of: str,
    scheduled_for: str,
    started_at: str,
    delayed: bool,
    delay_seconds: int,
) -> str:
    """渲染完整晨报 Markdown（含 Front Matter）。"""
    finished = now_iso()
    out: List[str] = _frontmatter(
        artifacts, report_date, window_start, window_end, as_of,
        scheduled_for, started_at, finished, delayed, delay_seconds)
    out += ["", f"# A股每日晨报 {report_date.isoformat()}", ""]

    # 执行说明
    out += ["## 执行说明", ""]
    out += [f"- 信息窗口：{window_start} 至 {window_end}"]
    out += [f"- 实际生成时间：{finished}"]
    out += [f"- 是否延迟：{'是' if delayed else '否'}{f'（延迟 {delay_seconds}s）' if delayed else ''}"]
    out += [f"- 数据覆盖状态：{'部分缺失' if artifacts.missing_data else '正常'}"]
    out += ["- 降级与缺失：" + ("；".join(artifacts.missing_data) or "无")]
    out += [""]

    # 一、重大必读（>=75 或强制纳入）
    must_read = [s for s in artifacts.scores
                 if s["final_score"] >= 75 or s["forced_include"]]
    out += ["## 一、重大必读", ""]
    if must_read:
        for s in must_read:
            c = next((x for x in artifacts.candidates if x.candidate_id == s["candidate_id"]), None)
            if c:
                out += [f"### {c.title}", "",
                        f"- **分数：**{s['final_score']:.0f}（{band_label(s['final_score'])}）",
                        f"- **分类：**{'/'.join(c.classification_path)}",
                        f"- **摘要：**{c.summary or c.title}", ""]
    else:
        out += ["本时间窗口内通过筛选的高价值信息有限。", ""]

    # 二至五、分类章节
    sections = _cluster_blocks(artifacts, {})
    grouped: Dict[str, List[str]] = {}
    for key, blocks in sections.items():
        section, _, _ = key.partition("###")
        grouped.setdefault(section, []).extend(blocks)
    major = ["二、宏观", "三、产业", "四、市场", "五、公司"]
    for i, m in enumerate(major):
        out += [f"## {m}", ""]
        subs = {k: v for k, v in grouped.items() if _major_of(k) == m}
        if subs:
            for label, blocks in subs.items():
                out += [f"### {label.split('###')[0]}", ""] + blocks
        else:
            out += ["本分类无合格信息（或数据缺失，不写无意义占位）。", ""]

    # 六、四个监测方向覆盖
    out += ["## 六、四个监测方向覆盖", ""]
    for ch in artifacts.coverage:
        out += [f"### {_channel_label(ch['monitoring_channel'])}", ""]
        out += [f"- 覆盖状态：{ch['status']}"]
        out += [f"- 使用来源：{', '.join(ch['sources_succeeded']) or '无'}"]
        out += [f"- 是否仅人工输入：{'是' if ch['status'] == 'manual_only' else '否'}"]
        out += [f"- 数据限制：{'; '.join(ch['limitations']) or '无'}", ""]

    # 七、隔夜外围总结
    out += ["## 七、隔夜外围总结", ""]
    out += [_OVERNIGHT_DEGRADED, ""]

    # 八、今日待验证事项
    out += ["## 八、今日待验证事项", ""]
    pending = _pending_items(artifacts)
    if pending:
        for p in pending:
            out += [f"- {p}"]
    else:
        out += ["- 无（本期候选均无明确待验证项）"]
    out += [""]

    # 九、未纳入正文的重要候选（55-64）
    appendix = [s for s in artifacts.scores if 55 <= s["final_score"] < 65]
    out += ["## 九、未纳入正文的重要候选", ""]
    if appendix:
        for s in appendix:
            c = next((x for x in artifacts.candidates if x.candidate_id == s["candidate_id"]), None)
            if c:
                out += [f"- {c.title}（{s['final_score']:.0f}分，候选观察）"]
    else:
        out += ["- 无"]
    out += [""]

    # 十、数据与来源说明
    out += ["## 十、数据与来源说明", ""]
    out += [f"- 实际成功来源：{_success_sources(artifacts)}"]
    out += [f"- 失败来源：{_failed_sources(artifacts)}"]
    out += ["- 缓存：未使用"]
    out += [f"- Manual Inbox：{'有' if _has_manual(artifacts) else '无'}"]
    out += [f"- 缺失数据：{'; '.join(artifacts.missing_data) or '无'}"]
    out += ["- 来源等级：S（法定披露）/A（政府公司官方）/B（财经媒体）/C（社区）/D（匿名）"]
    out += ["- 报告限制：LLM 语义细化环节尚未接入（确定性规则回退），"
            "新颖性/影响路径评分为确定性近似；事件聚类为确定性第一版"
            "（实体+日期预分桶+标题相似度），语义模型接入前不宣称语义聚类"]
    out += [""]
    return "\n".join(out)


def _major_of(label: str) -> str:
    mapping = {"宏观": "二、宏观", "产业": "三、产业", "市场": "四、市场", "公司": "五、公司"}
    for k, v in mapping.items():
        if k in label:
            return v
    return "其他"


def _channel_label(ch: str) -> str:
    return {
        "fast_news": "7×24快讯", "deep_financial_media": "财经媒体深度文章",
        "community_sentiment": "社区舆情", "institutional_activity": "机构动向",
    }.get(ch, ch)


def _pending_items(artifacts: PipelineArtifacts) -> List[str]:
    out: List[str] = []
    for cl in artifacts.clusters:
        for conflict in cl.conflicts:
            out.append(f"{cl.canonical_title[:40]}：{conflict}")
        if not cl.official_confirmation and cl.source_ids:
            out.append(f"{cl.canonical_title[:40]}：待官方披露确认")
    return out[:8]


def _success_sources(artifacts: PipelineArtifacts) -> str:
    sources = set()
    for c in artifacts.candidates:
        sources.update(c.source_ids)
    return ", ".join(sorted(sources)) or "无"


def _failed_sources(artifacts: PipelineArtifacts) -> str:
    return "无（本期未发起真实网络采集；CLS/CNINFO 适配器可用性见 source_coverage）"


def _has_manual(artifacts: PipelineArtifacts) -> bool:
    return any(c.monitoring_channel == "manual_submission" for c in artifacts.candidates)
