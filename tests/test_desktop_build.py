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
