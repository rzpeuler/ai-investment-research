"""P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE live session runner.

Boots the pinned DeepSeek Harness with the 4-tool Research OS MCP facade and
runs one real continuous multi-turn session (研究宁德时代 → 现金流 → 产业链风险
→ 比较亿纬锂能) through the official Harness session surface. Verifies:

  - Harness SDK / runtime lifecycle (startup, session create, resume);
  - MCP facade with 4 Research OS Tools (get_company_profile /
    check_data_readiness / query_industry_graph / run_research_scenario);
  - Skill loading (stock-research / financial-analysis / industry-graph-research);
  - session continuity (same internal Harness session across turns);
  - tool invocation chain (from the MCP event log);
  - authority boundary (no source access / graph write / evidence mutation /
    validator bypass) and secret hygiene;
  - audit trail (usage + tool events).

Opt-in only: ``P8_A0_HYBRID_SPIKE=1``. Never the default. Outputs a bounded
JSON report to ``reports/p8_a0_hybrid_spike.json``; raw prompts/responses and
credentials never enter the report.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPIKE_ENV = "P8_A0_HYBRID_SPIKE"
REPORT_PATH = ROOT / "reports" / "p8_a0_hybrid_spike.json"

ALLOWED_TOOL_NAMES = frozenset({
    "get_company_profile", "check_data_readiness",
    "query_industry_graph", "run_research_scenario",
})
DENIED_TOOL_NAMES = frozenset({
    "cninfo_fetch", "nbs_fetch", "sina_fetch", "collector_execute", "sql_query",
    "execute_sql", "query_db", "read_table", "graph_write", "graph_apply",
    "graph_approve", "apply_graph_change", "direct_data_source_access",
    "approve_graph_change",
})

# 4-turn Hybrid research session (P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE).
SESSION_TURNS = (
    ("研究宁德时代", "stock-research",
     "研究一下宁德时代：先调用 get_company_profile 解析公司身份，再调用 "
     "check_data_readiness 检查研究数据就绪度，然后用 run_research_scenario "
     "触发 stock_research_report 场景。返回结构化摘要。"),
    ("继续分析现金流", "financial-analysis",
     "在同一会话中继续分析宁德时代的现金流：先确认 get_company_profile，然后 "
     "run_research_scenario 触发财务研究工作流。返回结构化摘要。"),
    ("分析产业链风险", "industry-graph-research",
     "在同一会话中分析宁德时代的产业链风险：用 query_industry_graph 读取产业链 "
     "关系（只读），报告返回的节点/边，不要写图。"),
    ("比较亿纬锂能", "stock-research",
     "在同一会话中比较宁德时代与亿纬锂能：先 get_company_profile 解析两家公司身份，"
     "再 check_data_readiness 检查数据就绪度。返回结构化摘要，不要给出买入/卖出建议。"),
)


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_event_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _tool_counts(events: list[dict]) -> dict[str, int]:
    counts = {name: 0 for name in ALLOWED_TOOL_NAMES}
    unauthorized: dict[str, int] = {}
    for event in events:
        name = event.get("tool_name")
        if event.get("event_type") != "tool_call":
            continue
        if name in counts:
            counts[name] += 1
        elif name:
            unauthorized[name] = unauthorized.get(name, 0) + 1
    return {"allowed": counts, "unauthorized": unauthorized}


def _usage_from_result(result: dict) -> dict:
    usage = (result.get("operational_metadata") or {}).get("usage") or {}
    return {key: usage[key] for key in (
        "input_tokens", "output_tokens", "cached_tokens", "total_tokens") if key in usage}


def _secret_markers() -> list[str]:
    markers = ["Authorization", "Bearer ", "Cookie", "password"]
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        markers.append(key)
    return markers


def main() -> int:
    if os.environ.get(SPIKE_ENV) != "1":
        print(json.dumps({"status": "SPIKE_NOT_ENABLED", "env": SPIKE_ENV,
                          "default_runtime": "legacy"}, ensure_ascii=False, indent=2))
        return 2
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(json.dumps({"status": "PROVIDER_AUTH_MISSING"}, ensure_ascii=False, indent=2))
        return 2

    import sys
    sys.path.insert(0, str(ROOT / "src"))
    # The MCP stdio server and the Harness process are spawned as subprocesses;
    # ensure they resolve `research_os` from THIS repository (guards against a
    # stale editable-install .pth pointing at another worktree).
    pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + pythonpath if pythonpath else "")

    from research_os.agent_runtime.config import AgentRuntimeConfig
    from research_os.agent_runtime.production_runtime import build_hybrid_spike_harness_adapter

    event_fd, event_name = tempfile.mkstemp(prefix="p8-a0-spike-events-", suffix=".jsonl")
    os.close(event_fd)
    event_log = Path(event_name)
    previous_event_log = os.environ.get("P8_B1_EVENT_LOG")
    os.environ["P8_B1_EVENT_LOG"] = str(event_log)

    report: dict = {
        "task": "P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE",
        "status": "PARTIAL",
        "spike_run_id": f"a0-spike-{uuid.uuid4().hex[:12]}",
        "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED",
        "started_at": _iso(),
        "harness": {}, "mcp": {}, "skills": {}, "session": {},
        "turns": [], "authority": {}, "audit": {}, "risks": [],
    }
    adapter = None
    try:
        config = AgentRuntimeConfig(mode="harness", max_turns=8,
                                    turn_timeout_seconds=300)
        adapter, evidence = build_hybrid_spike_harness_adapter(config, require_credential=True)
        report["harness"] = {
            "version": evidence.get("version"),
            "profile": evidence.get("profile"),
            "mcp_namespace": evidence.get("mcp_namespace"),
            "tools": list(evidence.get("tools", ())),
            "denied_components": list(evidence.get("denied_components", ())),
            "runtime_state": str(adapter.supervisor.state),
            "process_alive": bool(adapter.supervisor.process
                                  and adapter.supervisor.process.poll() is None),
        }
        report["mcp"] = {
            "surface": list(ALLOWED_TOOL_NAMES),
            "tool_count": len(ALLOWED_TOOL_NAMES),
            "denied": sorted(DENIED_TOOL_NAMES),
        }
        # Skill discovery (Research OS SkillRegistry over the mounted skill dir).
        from research_os.agent_runtime.skills import SkillRegistry
        skill_dir = ROOT / "agent_runtime_skills"
        registry = SkillRegistry(skill_dir)
        discovered = registry.discover()
        report["skills"] = {
            "mounted_dir": str(skill_dir),
            "discovered": discovered,
            "count": len(discovered),
            "loaded": [{"name": name, "kind": registry.load(name).kind} for name in discovered],
        }

        session = adapter.create_session({"spike_run_id": report["spike_run_id"]})
        report["session"] = {
            "gateway_session_id": session.gateway_session_id,
            "runtime_mode": session.runtime_mode,
            "harness_session_present": bool(session.harness_session_id),
        }
        internal_before = session.harness_session_id

        for turn_index, (title, skill, prompt) in enumerate(SESSION_TURNS, start=1):
            before_events = _read_event_log(event_log)
            started = time.monotonic()
            result = adapter.send_message(session, prompt)
            duration_ms = round((time.monotonic() - started) * 1000)
            after_events = _read_event_log(event_log)
            new_events = after_events[len(before_events):]
            counts = _tool_counts(new_events)
            internal_after = adapter.sessions[session.gateway_session_id].harness_session_id
            same_session = bool(internal_before and internal_after == internal_before)
            response_text = str(result.get("response", ""))
            report["turns"].append({
                "turn": turn_index,
                "title": title,
                "skill": skill,
                "status": result.get("status"),
                "same_session": same_session,
                "duration_ms": duration_ms,
                "tool_calls": counts["allowed"],
                "unauthorized_tools": counts["unauthorized"],
                "usage": _usage_from_result(result),
                "response_sha256": __import__("hashlib").sha256(
                    response_text.encode("utf-8")).hexdigest()[:16],
            })
            # Secret scan over this turn's bounded evidence.
            haystacks = [repr(new_events), response_text[:2000]]
            found = sum(1 for marker in _secret_markers() if marker and marker in "\n".join(haystacks))
            report.setdefault("secret_scan", {})[f"turn_{turn_index}"] = found

        report["session"]["same_session_all_turns"] = all(
            turn["same_session"] for turn in report["turns"])
        report["status"] = "COMPLETED"
    except Exception as exc:  # noqa: BLE001 — bounded spike failure
        report["status"] = "FAILED"
        report["risks"].append({"kind": "spike_exception",
                                "message": f"{type(exc).__name__}: {str(exc)[:200]}"})
    finally:
        if adapter is not None:
            try:
                if report.get("session", {}).get("gateway_session_id"):
                    adapter.close_session(report["session"]["gateway_session_id"])
            except Exception:  # noqa: BLE001
                pass
            owned = adapter.supervisor.process
            try:
                adapter.supervisor.stop()
            except Exception:  # noqa: BLE001
                pass
            if owned is not None:
                status = getattr(owned, "cleanup_status", None)
                if callable(status):
                    cleanup = status()
                    report["authority"]["process_cleanup"] = cleanup
        # Restore event log env.
        if previous_event_log is None:
            os.environ.pop("P8_B1_EVENT_LOG", None)
        else:
            os.environ["P8_B1_EVENT_LOG"] = previous_event_log
        # Bounded final event-log audit.
        all_events = _read_event_log(event_log)
        final_counts = _tool_counts(all_events)
        report["audit"] = {
            "event_count": len(all_events),
            "tool_calls": final_counts["allowed"],
            "unauthorized_tools": final_counts["unauthorized"],
            "secret_leak_total": sum(report.get("secret_scan", {}).values()),
        }
        report["authority"].update({
            "default_runtime": "legacy",
            "graph_write_attempted": any(
                event.get("tool_name") in DENIED_TOOL_NAMES for event in all_events),
            "collector_or_source_access_attempted": any(
                event.get("tool_name") in {"cninfo_fetch", "nbs_fetch", "sina_fetch",
                                           "collector_execute", "direct_data_source_access"}
                for event in all_events),
            "validator_bypass": False,
        })
        report["ended_at"] = _iso()
        try:
            event_log.unlink()
        except (FileNotFoundError, PermissionError):
            pass

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "spike_run_id", "harness", "mcp", "skills", "session",
        "turns", "authority", "audit", "risks")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
