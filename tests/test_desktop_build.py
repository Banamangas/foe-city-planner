"""desktop/build.py installs the frontend packages on a fresh checkout."""
import importlib.util
from pathlib import Path

import pytest

_BUILD = Path(__file__).resolve().parent.parent / "desktop" / "build.py"


@pytest.fixture
def build(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("desktop_build", _BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "frontend").mkdir()
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/bin/npm")
    calls = []

    def run(cmd, cwd, check):
        calls.append(cmd[1:])
        if cmd[1:] == ["run", "build"]:
            (tmp_path / "webapp" / "dist").mkdir(parents=True)
            (tmp_path / "webapp" / "dist" / "index.html").write_text("x")
    monkeypatch.setattr(mod.subprocess, "run", run)
    return mod, tmp_path, calls


def test_fresh_checkout_runs_npm_ci_first(build):
    mod, _, calls = build
    mod.build_frontend()
    assert calls == [["ci"], ["run", "build"]]


def test_existing_node_modules_skips_npm_ci(build):
    mod, root, calls = build
    (root / "frontend" / "node_modules").mkdir()
    mod.build_frontend()
    assert calls == [["run", "build"]]


_ROOT = _BUILD.parent.parent


def _pins() -> dict[str, str]:
    """name -> the whole requirement line of desktop/requirements-build.txt."""
    lines = (_ROOT / "desktop" / "requirements-build.txt").read_text().splitlines()
    reqs = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return {r.split("==")[0].strip().lower(): r for r in reqs}


def test_build_requirements_are_all_exact():
    pins = _pins()
    for line in pins.values():
        spec = line.split(";")[0]            # the marker may hold "!="
        assert "==" in spec and not any(op in spec for op in (">", "<", "~", "!", ",")), line
    for name in ("flask", "werkzeug", "ortools", "numpy", "pandas", "pyinstaller", "pywebview"):
        assert name in pins, name
    assert pins["pyinstaller"].startswith("pyinstaller==6.22.3")
    assert pins["pywebview"] == "pywebview==6.2.1 ; sys_platform != 'linux'"


def test_build_pins_match_uv_lock():
    """The app's own packages are built at the versions the tests run with."""
    import tomllib
    lock = tomllib.loads((_ROOT / "uv.lock").read_text())
    locked = {p["name"].lower(): p["version"] for p in lock["package"]}
    for name in ("flask", "werkzeug", "ortools", "numpy", "pandas", "pywebview", "protobuf"):
        assert _pins()[name].split(";")[0].strip() == f"{name}=={locked[name]}", name


def test_workflow_installs_the_pinned_file():
    wf = (_ROOT / ".github" / "workflows" / "desktop.yml").read_text()
    assert "pip install -r desktop/requirements-build.txt" in wf
    assert ">=" not in wf
