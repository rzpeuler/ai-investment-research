from click.testing import CliRunner

from research_os.cli.main import cli


def test_dashboard_rejects_invalid_ports(monkeypatch, tmp_path):
    (tmp_path / "schemas").mkdir()
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(tmp_path))
    for value in ("0", "65536"):
        result = CliRunner().invoke(cli, ["dashboard", "--port", value, "--no-browser"])
        assert result.exit_code != 0


def test_dashboard_cli_wires_loopback_and_closes(monkeypatch, tmp_path):
    (tmp_path / "schemas").mkdir()
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(tmp_path))
    events = []
    class Server:
        server_port = 4321
        def serve_forever(self): raise KeyboardInterrupt
        def shutdown(self): events.append("shutdown")
        def server_close(self): events.append("close")
    monkeypatch.setattr("research_os.dashboard.runtime.build_dashboard_runtime", lambda root: (object(), False, None))
    monkeypatch.setattr("research_os.dashboard.server.create_server", lambda app, port: Server())
    result = CliRunner().invoke(cli, ["dashboard", "--port", "4321", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:4321/" in result.output and "LLM configured: False" in result.output
    assert events == ["close"]
