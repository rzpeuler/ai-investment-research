import http.client
import json
import socket
import threading
from dataclasses import asdict
from pathlib import Path

import pytest

from research_os.dashboard.app import DashboardApplication
from research_os.dashboard.models import ChatResult
from research_os.dashboard.server import create_server
from research_os.dashboard.session import SessionStore


class FakeChatService:
    def __init__(self, project_root=None):
        self.project_root = Path(project_root) if project_root else None

    def handle(self, request):
        run_dir = str(self.project_root / "reports" / "runs" / "secret") if self.project_root else "run"
        report_path = str(self.project_root / "reports" / "ok.md") if self.project_root else "reports/ok.md"
        return ChatResult(
            "executed", "完成", scenario=request.selected_scenario,
            public_draft={
                "complete": True,
                "nested": {"base_url": "https://secret.invalid/v1", "note": run_dir},
            },
            minimal_request={
                "research_live": request.research_live,
                "private_path": run_dir,
                "api_key": "never-return-this",
            },
            research_result={
                "status": "degraded", "exit_code": 0, "task_id": "task-safe",
                "run_dir": run_dir, "report_path": report_path,
                "missing_data": ["x"], "model_route": {"base_url": "https://secret.invalid/v1"},
                "message": f"完成 {run_dir}",
            },
            reference_now="2026-08-10T09:30:00",
        )


@pytest.fixture()
def http_server(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "ok.md").write_text("# 报告", encoding="utf-8")
    app = DashboardApplication(tmp_path, FakeChatService(tmp_path), SessionStore(), llm_configured=False)
    server = create_server(app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown(); server.server_close(); thread.join(timeout=2)


def request(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    payload = response.read()
    result = response.status, dict(response.getheaders()), payload
    conn.close()
    return result


def raw_request(server, request_bytes):
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as sock:
        sock.sendall(request_bytes)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def test_static_meta_health_and_unknown_route(http_server):
    status, headers, body = request(http_server, "GET", "/")
    assert status == 200 and b"AI" in body
    assert headers["X-Content-Type-Options"] == "nosniff"
    status, headers, body = request(http_server, "GET", "/api/meta")
    meta = json.loads(body)
    assert status == 200 and meta["scenarios"][0]["id"] == "AUTO"
    assert meta["llm_configured"] is False
    assert "provider_status" not in meta
    assert "base_url" not in body.decode().lower()
    assert headers["Cache-Control"] == "no-store"
    assert request(http_server, "GET", "/api/health")[0] == 200
    status, _, body = request(http_server, "GET", "/nope")
    assert status == 404 and json.loads(body)["error"]["code"] == "NOT_FOUND"
    assert request(http_server, "POST", "/api/meta", b"{}", {"Content-Type": "application/json"})[0] == 405
    assert request(http_server, "OPTIONS", "/api/meta")[0] == 405


def test_chat_validation_and_session_isolation(http_server):
    valid = json.dumps({"session_id": "s1", "message": "今天晨报", "selected_scenario": "morning_brief", "llm_enabled": False, "research_live": True}).encode()
    status, _, body = request(http_server, "POST", "/api/chat", valid, {"Content-Type": "application/json; charset=utf-8"})
    payload = json.loads(body)
    assert status == 200 and payload["status"] == "executed"
    assert payload["report"] == "ok.md" and payload["missing"] == ["x"]
    serialized = body.decode("utf-8")
    assert str(http_server.app.project_root) not in serialized
    assert "secret.invalid" not in serialized
    assert "never-return-this" not in serialized and "api_key" not in serialized
    assert "run_dir" not in payload["result"] and "report_path" not in payload["result"]
    recent_body = request(http_server, "GET", "/api/recent?session_id=s1")[2]
    assert len(json.loads(recent_body)["turns"]) == 1
    assert str(http_server.app.project_root) not in recent_body.decode("utf-8")
    assert "secret.invalid" not in recent_body.decode("utf-8")
    assert json.loads(request(http_server, "GET", "/api/recent?session_id=s2")[2])["turns"] == []

    bad_cases = [
        (b"{}", {"Content-Type": "text/plain"}, 415),
        (b"{", {"Content-Type": "application/json"}, 400),
        (json.dumps({"session_id": "s", "message": "x", "selected_scenario": "bad", "llm_enabled": False, "research_live": False}).encode(), {"Content-Type": "application/json"}, 422),
        (json.dumps({"session_id": "s", "message": "x", "selected_scenario": "AUTO", "llm_enabled": 1, "research_live": False}).encode(), {"Content-Type": "application/json"}, 422),
    ]
    for body, headers, expected in bad_cases:
        assert request(http_server, "POST", "/api/chat", body, headers)[0] == expected


def test_chat_content_length_and_body_limit_fail_closed(http_server):
    prefix = b"POST /api/chat HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nConnection: close\r\n"
    assert b" 411 " in raw_request(http_server, prefix + b"\r\n{}")
    assert b" 400 " in raw_request(http_server, prefix + b"Content-Length: nope\r\n\r\n")
    assert b" 413 " in raw_request(http_server, prefix + b"Content-Length: 65537\r\n\r\n")
    framing_cases = [
        prefix + b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        prefix + b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        prefix + b"Transfer-Encoding: chunked\r\nContent-Length: 2\r\n\r\n{}",
    ]
    for raw in framing_cases:
        response = raw_request(http_server, raw)
        assert b" 400 " in response and b"Connection: close" in response
    get_with_te = raw_request(
        http_server,
        b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n0\r\n\r\n",
    )
    assert b" 400 " in get_with_te and b"Connection: close" in get_with_te


@pytest.mark.parametrize("content_type", [
    "application/json; charset=utf-16", "application/json; foo=bar",
    "application/json; charset=utf-8; foo=bar", "application/json; charset=utf-8; charset=utf-8",
])
def test_chat_rejects_unsupported_content_type_parameters(http_server, content_type):
    assert request(http_server, "POST", "/api/chat", b"{}", {"Content-Type": content_type})[0] == 415


@pytest.mark.parametrize("path", [
    "/api/recent?session_id=s&extra=x", "/api/recent?session_id=s&session_id=s",
    "/api/report?path=ok.md&extra=x", "/api/report?path=ok.md&path=ok.md",
    "/api/report?token=ok.md&path=ok.md",
])
def test_api_query_contract_rejects_extra_or_duplicate_keys(http_server, path):
    assert request(http_server, "GET", path)[0] == 400


@pytest.mark.parametrize("attack", ["../pyproject.toml", "%2e%2e%2fpyproject.toml", "/etc/passwd", "ok.md%00", ".", "missing.md"])
def test_report_reader_fails_closed(http_server, attack):
    assert request(http_server, "GET", f"/api/report?path={attack}")[0] in {400, 404}


def test_report_reader_only_serves_plain_file_under_reports(http_server):
    status, headers, body = request(http_server, "GET", "/api/report?path=ok.md")
    assert status == 200 and body.decode() == "# 报告"
    assert headers["Content-Type"].startswith("text/plain")


def test_report_reader_rejects_symlink_escape(http_server, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = http_server.app.reports_root / "escape.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this Windows host")
    assert request(http_server, "GET", "/api/report?path=escape.md")[0] == 400


def test_server_factory_has_no_host_escape_hatch(tmp_path):
    app = DashboardApplication(tmp_path, FakeChatService(), SessionStore(), llm_configured=False)
    with pytest.raises(TypeError):
        create_server(app, port=0, host="0.0.0.0")
