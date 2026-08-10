from importlib import resources
from pathlib import Path
import tomllib


def test_dashboard_static_assets_are_package_resources():
    static = resources.files("research_os.dashboard").joinpath("static")
    for name in ("index.html", "dashboard.js", "dashboard.css"):
        assert static.joinpath(name).is_file()
        assert static.joinpath(name).read_bytes()


def test_wheel_configuration_force_includes_dashboard_static_assets():
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["src/research_os/dashboard/static"] == "research_os/dashboard/static"


def test_dashboard_frontend_guards_inflight_and_stale_responses():
    script = resources.files("research_os.dashboard").joinpath("static", "dashboard.js").read_text("utf-8")
    assert "submitButton.disabled=true" in script
    assert '$("message").disabled=true' in script
    assert "sequence!==latestRequestSequence" in script
    assert "sequence===latestRequestSequence" in script
