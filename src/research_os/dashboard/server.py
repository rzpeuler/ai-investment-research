"""Loopback-only stdlib HTTP server."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from research_os.dashboard.app import ApiError, MAX_JSON_BODY_BYTES


class _DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_close(self):
        try:
            close = getattr(self.app, "close", None)
            if close:
                close()
        finally:
            super().server_close()


class _Handler(BaseHTTPRequestHandler):
    server_version = "ResearchDashboard"
    sys_version = ""

    def do_GET(self):
        self._dispatch(b"")

    def do_POST(self):
        try:
            transfer_encodings = self.headers.get_all("Transfer-Encoding") or []
            if transfer_encodings:
                raise ApiError(400, "TRANSFER_ENCODING_NOT_ALLOWED", "不接受 Transfer-Encoding。")
            lengths = self.headers.get_all("Content-Length") or []
            if not lengths:
                raise ApiError(411, "CONTENT_LENGTH_REQUIRED", "缺少 Content-Length。")
            if len(lengths) != 1:
                raise ApiError(400, "DUPLICATE_CONTENT_LENGTH", "不得重复 Content-Length。")
            raw_length = lengths[0]
            try:
                length = int(raw_length)
            except ValueError:
                raise ApiError(400, "INVALID_CONTENT_LENGTH", "Content-Length 非法。") from None
            if length < 0:
                raise ApiError(400, "INVALID_CONTENT_LENGTH", "Content-Length 非法。")
            if length > MAX_JSON_BODY_BYTES:
                raise ApiError(413, "BODY_TOO_LARGE", "请求体超过大小限制。")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ApiError(400, "INCOMPLETE_BODY", "请求体长度不完整。")
            self._dispatch(body)
        except ApiError as error:
            self.close_connection = True
            self._write(*self.server.app.error_response(error))

    def do_PUT(self): self._dispatch(b"")
    def do_DELETE(self): self._dispatch(b"")
    def do_PATCH(self): self._dispatch(b"")
    def do_HEAD(self): self._dispatch(b"")
    def do_OPTIONS(self): self._dispatch(b"")
    def do_TRACE(self): self._dispatch(b"")
    def do_CONNECT(self): self._dispatch(b"")

    def _dispatch(self, body):
        try:
            if self.headers.get_all("Transfer-Encoding"):
                self.close_connection = True
                raise ApiError(400, "TRANSFER_ENCODING_NOT_ALLOWED", "不接受 Transfer-Encoding。")
            if len(self.headers.get_all("Content-Length") or []) > 1:
                self.close_connection = True
                raise ApiError(400, "DUPLICATE_CONTENT_LENGTH", "不得重复 Content-Length。")
            response = self.server.app.dispatch(self.command, self.path, self.headers, body)
        except ApiError as error:
            response = self.server.app.error_response(error)
        except Exception:
            response = self.server.app.error_response(ApiError(500, "INTERNAL_ERROR", "服务器内部错误。"))
        self._write(*response)

    def _write(self, status, headers, body):
        self.send_response(status)
        headers = dict(headers)
        headers["Content-Length"] = str(len(body))
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'"
        if self.path.startswith("/api/"):
            headers["Cache-Control"] = "no-store"
        if self.close_connection:
            headers["Connection"] = "close"
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format, *args):
        return


def create_server(app, port: int = 8765):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be 0-65535 (0 is test-only ephemeral bind)")
    server = _DashboardServer(("127.0.0.1", port), _Handler)
    server.app = app
    return server
