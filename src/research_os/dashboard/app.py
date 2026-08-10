"""Transport-neutral routing and validation for the local dashboard."""
from __future__ import annotations

from dataclasses import asdict
from importlib import resources
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from research_os import __version__
from research_os.dashboard.models import ChatRequest
from research_os.dashboard.scenario_specs import CHAT_SCENARIO_SPECS

MAX_JSON_BODY_BYTES = 64 * 1024
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|\\\\)[^\r\n\t\"'<>]*"
)
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![:/A-Za-z0-9])/(?:[^/\s]+/)*[^,\s;\"'<>]*"
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "authorization", "base_url", "password", "secret", "token",
})


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class DashboardApplication:
    def __init__(self, project_root: str | Path, chat_service: Any, sessions: Any,
                 *, llm_configured: bool, close_callback=None):
        self.project_root = Path(project_root).resolve()
        self.reports_root = (self.project_root / "reports").resolve()
        self.chat_service = chat_service
        self.sessions = sessions
        self.llm_configured = bool(llm_configured)
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
                self._require_empty_query(target.query)
                return self._json(200, self._meta())
            if method == "GET" and path == "/api/health":
                self._require_empty_query(target.query)
                return self._json(200, {
                    "status": "ok", "version": __version__,
                    "llm_configured": self.llm_configured,
                })
            if method == "GET" and path == "/api/recent":
                session_id = self._single_query(target.query, ("session_id",))
                self._validate_session_id(session_id)
                return self._json(200, {
                    "session_id": session_id,
                    "turns": self._sanitize_json(self.sessions.recent(session_id)),
                })
            if method == "GET" and path == "/api/report":
                report_path = self._single_query(target.query, ("path",))
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
        scenarios.extend(
            {"id": scenario_id, "label": spec.display_label}
            for scenario_id, spec in CHAT_SCENARIO_SPECS.items()
        )
        return {"version": __version__, "scenarios": scenarios,
                "llm_configured": self.llm_configured,
                "capabilities": {"research_live": True, "session_storage": "IN_MEMORY_ONLY"}}

    def _chat(self, headers: Any, body: bytes):
        content_types = headers.get_all("Content-Type") if hasattr(headers, "get_all") else [headers.get("Content-Type")]
        if len(content_types) != 1 or not self._is_allowed_json_content_type(content_types[0]):
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "POST /api/chat 仅接受 application/json。")
        if len(body) > MAX_JSON_BODY_BYTES:
            raise ApiError(413, "BODY_TOO_LARGE", "请求体超过大小限制。")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "MALFORMED_JSON", "请求体不是合法 UTF-8 JSON。") from None
        request_payload = self._validate_chat_payload(payload)
        session_id = request_payload["session_id"]
        if not self.sessions.try_begin(session_id):
            raise ApiError(409, "SESSION_BUSY", "该会话正在处理上一条请求。")
        try:
            context = self.sessions.context(
                session_id, request_payload["selected_scenario"],
            )
            chat_request = ChatRequest(
                message=request_payload["message"], selected_scenario=request_payload["selected_scenario"],
                llm_enabled=request_payload["llm_enabled"] and self.llm_configured,
                research_live=request_payload["research_live"],
                session_context=context,
            )
            result = self.chat_service.handle(
                chat_request, conversation_context=context,
            )
            raw = asdict(result)
            research = raw["research_result"] or {}
            report = self._safe_report_reference(research.get("report_path"))
            response = {
                "status": self._public_text(raw["state"]),
                "message": self._public_text(raw["message"]),
                "recognized": {
                    "scenario": raw["scenario"] if raw["scenario"] in CHAT_SCENARIO_SPECS else None,
                    "reference_now": self._public_text(raw["reference_now"]),
                    "llm_calls": raw["llm_calls"] if type(raw["llm_calls"]) is int else 0,
                },
                "draft": self._sanitize_json(raw["public_draft"]),
                "minimal_request": self._sanitize_json(raw["minimal_request"]),
                "result": self._public_research_result(research),
                "report": report,
                "missing": self._public_string_list(research.get("missing_data")),
            }
            self.sessions.record_turn(session_id, self._sanitize_json(request_payload), response)
            return self._json(200, response)
        finally:
            self.sessions.end(session_id)

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
    def _single_query(query: str, allowed_names: tuple[str, ...]) -> str:
        pairs = parse_qsl(query, keep_blank_values=True)
        if len(pairs) != 1 or pairs[0][0] not in allowed_names:
            names = "/".join(allowed_names)
            raise ApiError(400, "INVALID_QUERY", f"必须且只能提供一个 {names} 参数。")
        return pairs[0][1]

    @staticmethod
    def _require_empty_query(query: str) -> None:
        if query:
            raise ApiError(400, "INVALID_QUERY", "该 API 不接受 query 参数。")

    @staticmethod
    def _is_allowed_json_content_type(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        parts = [part.strip() for part in value.split(";")]
        if not parts or parts[0].casefold() != "application/json":
            return False
        if len(parts) == 1:
            return True
        if len(parts) != 2 or not parts[1] or "=" not in parts[1]:
            return False
        name, parameter = (item.strip() for item in parts[1].split("=", 1))
        if name.casefold() != "charset":
            return False
        if len(parameter) >= 2 and parameter[0] == parameter[-1] and parameter[0] in "\"'":
            parameter = parameter[1:-1]
        return parameter.casefold() == "utf-8"

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

    def _public_research_result(self, result: Any) -> dict[str, Any] | None:
        if not isinstance(result, dict) or not result:
            return None
        public: dict[str, Any] = {}
        for field in ("status", "validation_status", "message"):
            if isinstance(result.get(field), str):
                public[field] = self._public_text(result[field])
        for field in ("task_id", "run_id"):
            value = result.get(field)
            public[field] = value if isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value) else None
        if type(result.get("exit_code")) is int:
            public["exit_code"] = result["exit_code"]
        runtime_seconds = result.get("runtime_seconds")
        if isinstance(runtime_seconds, (int, float)) and not isinstance(runtime_seconds, bool):
            public["runtime_seconds"] = (
                runtime_seconds if math.isfinite(runtime_seconds) else None
            )
        public["warnings"] = self._public_string_list(result.get("warnings"))
        public["missing_data"] = self._public_string_list(result.get("missing_data"))
        return public

    def _public_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [self._public_text(item) for item in value if isinstance(item, str)][:100]

    def _public_text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = value
        for root in {str(self.project_root), self.project_root.as_posix()}:
            text = text.replace(root, "[REDACTED_PATH]")
        text = _WINDOWS_ABSOLUTE_PATH.sub("[REDACTED_PATH]", text)
        return _POSIX_ABSOLUTE_PATH.sub("[REDACTED_PATH]", text)

    def _sanitize_json(self, value: Any) -> Any:
        if value is None or type(value) in {bool, int}:
            return value
        if type(value) is float:
            return value if math.isfinite(value) else None
        if isinstance(value, str):
            return self._public_text(value)
        if isinstance(value, (list, tuple)):
            return [self._sanitize_json(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._sanitize_json(item)
                for key, item in value.items()
                if str(key).casefold() not in _SENSITIVE_KEYS
            }
        return None

    @staticmethod
    def _json(status: int, payload: dict[str, Any]):
        try:
            body = json.dumps(
                payload, ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            status = 500
            body = json.dumps({
                "error": {
                    "code": "SERIALIZATION_ERROR",
                    "message": "响应序列化失败。",
                },
            }, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return status, {"Content-Type": "application/json; charset=utf-8"}, body
