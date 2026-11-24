import os
import sys

from desktop.paths import data_dir


def test_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom" / "data"
    monkeypatch.setenv("FOEOPT_DATA_DIR", str(target))
    assert data_dir() == str(target)
    assert target.is_dir()


def _clean(monkeypatch):
    for k in ("FOEOPT_DATA_DIR", "LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(k, raising=False)


def test_windows(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert data_dir() == os.path.join(str(tmp_path), "foe-city-planner")
    assert os.path.isdir(data_dir())


def test_macos(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = os.path.join(str(tmp_path), "Library", "Application Support", "foe-city-planner")
    assert data_dir() == expected
    assert os.path.isdir(expected)


def test_linux_xdg(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert data_dir() == os.path.join(str(tmp_path), "foe-city-planner")


def test_linux_default(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = os.path.join(str(tmp_path), ".local", "share", "foe-city-planner")
    assert data_dir() == expected
    assert os.path.isdir(expected)
