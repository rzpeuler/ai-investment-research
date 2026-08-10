"""Transport-neutral routing and validation for the local dashboard."""
from __future__ import annotations

from dataclasses import asdict
from importlib import resources
import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit

from research_os import __version__
from research_os.dashboard.models import ChatRequest
from research_os.dashboard.scenario_specs import CHAT_SCENARIO_SPECS
from research_os.orchestrator.runners import DEFAULT_SCENARIOS

MAX_JSON_BODY_BYTES = 64 * 1024
SCENARIO_LABELS = {
    "morning_brief": "每日晨报", "abnormal_move_analysis": "异动分析",
    "stock_research_report": "个股研报", "evening_brief": "每日晚报",
    "daily_review": "每日复盘", "stock_review": "个股复盘",
    "industry_research": "行业研究", "theme_discovery": "主题发现",
    "earnings_expectation": "财报预期", "first_coverage": "首次覆盖",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class DashboardApplication:
    def __init__(self, project_root: str | Path, chat_service: Any, sessions: Any,
                 *, llm_configured: bool, provider_status: str = "not_configured",
                 close_callback=None):
        self.project_root = Path(project_root).resolve()
        self.reports_root = (self.project_root / "reports").resolve()
        self.chat_service = chat_service
        self.sessions = sessions
        self.llm_configured = bool(llm_configured)
        self.provider_status = provider_status
        self._close_callback = close_callback

    def close(self) -> None:
        if self._close_callback is not None:
            callback, self._close_callback = self._close_callback, None
            callback()

    def dispatch(self, method: str, raw_target: str, headers: Any, body: bytes = b""):
        target = urlsplit(raw_target)
        path = target.path
        if path.startswith("/api/"):
            if method == "GET" and path == "/api/meta":
                return self._json(200, self._meta())
            if method == "GET" and path == "/api/health":
                return self._json(200, {"status": "ok", "version": __version__, "provider_status": self.provider_status})
            if method == "GET" and path == "/api/recent":
                session_id = self._single_query(target.query, "session_id")
                self._validate_session_id(session_id)
                return self._json(200, {"session_id": session_id, "turns": self.sessions.recent(session_id)})
            if method == "GET" and path == "/api/report":
                report_path = self._single_query(target.query, "path")
                data = self._read_report(report_path)
                return 200, {"Content-Type": "text/plain; charset=utf-8"}, data
            if method == "POST" and path == "/api/chat":
                return self._chat(headers, body)
            known = {"/api/meta", "/api/health", "/api/recent", "/api/report", "/api/chat"}
            if path in known:
                raise ApiError(405, "METHOD_NOT_ALLOWED", "该 API 不支持此 HTTP method。")
            raise ApiError(404, "NOT_FOUND", "路径不存在。")
        if method != "GET":
            if path in {"/", "/dashboard.js", "/dashboard.css"}:
                raise ApiError(405, "METHOD_NOT_ALLOWED", "静态资源仅支持 GET。")
            raise ApiError(404, "NOT_FOUND", "路径不存在。")
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
                  "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8")}
        if path not in assets:
            raise ApiError(404, "NOT_FOUND", "路径不存在。")
        name, content_type = assets[path]
        data = resources.files("research_os.dashboard").joinpath("static", name).read_bytes()
        return 200, {"Content-Type": content_type}, data

    def error_response(self, error: ApiError):
        return self._json(error.status, {"error": {"code": error.code, "message": error.message}})

    def _meta(self) -> dict[str, Any]:
        scenarios = [{"id": "AUTO", "label": "自动识别"}]
        scenarios.extend({"id": item, "label": SCENARIO_LABELS[item]} for item in DEFAULT_SCENARIOS)
        return {"version": __version__, "scenarios": scenarios,
                "llm_configured": self.llm_configured,
                "provider_status": self.provider_status,
                "capabilities": {"research_live": True, "session_storage": "IN_MEMORY_ONLY"}}

    def _chat(self, headers: Any, body: bytes):
        content_type = (headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "POST /api/chat 仅接受 application/json。")
        if len(body) > MAX_JSON_BODY_BYTES:
            raise ApiError(413, "BODY_TOO_LARGE", "请求体超过大小限制。")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "MALFORMED_JSON", "请求体不是合法 UTF-8 JSON。") from None
        request_payload = self._validate_chat_payload(payload)
        session_id = request_payload["session_id"]
        chat_request = ChatRequest(
            message=request_payload["message"], selected_scenario=request_payload["selected_scenario"],
            llm_enabled=request_payload["llm_enabled"] and self.llm_configured,
            research_live=request_payload["research_live"],
            session_context=self.sessions.context(session_id),
        )
        result = self.chat_service.handle(chat_request)
        raw = asdict(result)
        research = raw["research_result"] or {}
        report = self._safe_report_reference(research.get("report_path"))
        response = {
            "status": raw["state"], "message": raw["message"],
            "recognized": {"scenario": raw["scenario"], "reference_now": raw["reference_now"], "llm_calls": raw["llm_calls"]},
            "draft": raw["public_draft"], "minimal_request": raw["minimal_request"],
            "result": raw["research_result"], "report": report,
            "missing": research.get("missing_data") or [],
        }
        self.sessions.record_turn(session_id, request_payload, response)
        return self._json(200, response)

    def _validate_chat_payload(self, payload: Any) -> dict[str, Any]:
        keys = {"session_id", "message", "selected_scenario", "llm_enabled", "research_live"}
        if not isinstance(payload, dict) or set(payload) != keys:
            raise ApiError(422, "INVALID_FIELDS", "请求字段必须严格匹配 API 契约。")
        self._validate_session_id(payload["session_id"])
        if not isinstance(payload["message"], str) or not payload["message"].strip() or len(payload["message"]) > 10000:
            raise ApiError(422, "INVALID_MESSAGE", "message 必须是非空且长度合理的字符串。")
        scenario = payload["selected_scenario"]
        if scenario is not None and scenario not in {"AUTO", *CHAT_SCENARIO_SPECS}:
            raise ApiError(422, "INVALID_SCENARIO", "selected_scenario 不在允许集合中。")
        if type(payload["llm_enabled"]) is not bool or type(payload["research_live"]) is not bool:
            raise ApiError(422, "INVALID_SWITCH", "LLM 和 Research Live 开关必须是布尔值。")
        return payload

    @staticmethod
    def _validate_session_id(value: Any) -> None:
        if not isinstance(value, str) or not value or len(value) > 128 or not all(c.isalnum() or c in "-_" for c in value):
            raise ApiError(422, "INVALID_SESSION_ID", "session_id 格式非法。")

    @staticmethod
    def _single_query(query: str, name: str) -> str:
        values = parse_qs(query, keep_blank_values=True).get(name)
        if values is None or len(values) != 1:
            raise ApiError(400, "INVALID_QUERY", f"必须提供唯一 {name} 参数。")
        return values[0]

    def _read_report(self, value: str) -> bytes:
        if not value or "\x00" in value or Path(value).is_absolute() or PurePosixPath(value).is_absolute():
            raise ApiError(400, "INVALID_REPORT_PATH", "报告路径非法。")
        candidate = (self.reports_root / Path(value)).resolve()
        try:
            candidate.relative_to(self.reports_root)
        except ValueError:
            raise ApiError(400, "REPORT_PATH_ESCAPE", "报告路径越界。") from None
        if not candidate.exists():
            raise ApiError(404, "REPORT_NOT_FOUND", "报告不存在。")
        if not candidate.is_file():
            raise ApiError(400, "REPORT_NOT_FILE", "报告路径不是普通文件。")
        try:
            return candidate.read_bytes().decode("utf-8").encode("utf-8")
        except UnicodeDecodeError:
            raise ApiError(415, "REPORT_NOT_UTF8", "报告不是 UTF-8 文本。") from None

    def _safe_report_reference(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        path = Path(value)
        candidate = path.resolve() if path.is_absolute() else (self.project_root / path).resolve()
        try:
            relative = candidate.relative_to(self.reports_root)
        except ValueError:
            return None
        return relative.as_posix()

    @staticmethod
    def _json(status: int, payload: dict[str, Any]):
        return status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(payload, ensure_ascii=False).encode("utf-8")
