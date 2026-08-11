from importlib import resources
from pathlib import Path
import tomllib


def test_dashboard_static_assets_are_package_resources():
    static = resources.files("research_os.dashboard").joinpath("static")
    for name in ("index.html", "dashboard.js", "dashboard.css"):
        assert static.joinpath(name).is_file()
        assert static.joinpath(name).read_bytes()


def test_wheel_configuration_packages_dashboard_without_duplicate_force_include():
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/research_os"]
    assert "force-include" not in wheel


def test_dashboard_frontend_guards_inflight_and_stale_responses():
    script = resources.files("research_os.dashboard").joinpath("static", "dashboard.js").read_text("utf-8")
    assert "submitButton.disabled=true" in script
    assert '$("message").disabled=true' in script
    assert "sequence!==latestRequestSequence" in script
    assert "sequence===latestRequestSequence" in script
