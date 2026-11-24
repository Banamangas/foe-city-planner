"""The self-test checks the window backend is in Windows and macOS builds."""
import sys
import types

import pytest

from desktop import selftest


def _fake_backend(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


def _block_import(monkeypatch, name):
    # None in sys.modules makes `import name` raise ImportError.
    monkeypatch.setitem(sys.modules, name, None)


def test_linux_skips_the_window_check(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    _block_import(monkeypatch, "webview.platforms.winforms")
    _block_import(monkeypatch, "webview.platforms.cocoa")
    assert selftest._window_problem() is None


def test_windows_edge_backend_passes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _fake_backend(monkeypatch, "webview.platforms.winforms", renderer="edgechromium")
    assert selftest._window_problem() is None


@pytest.mark.parametrize("attrs", [{"renderer": "mshtml"}, {}])
def test_windows_wrong_renderer_fails(monkeypatch, attrs):
    monkeypatch.setattr(sys, "platform", "win32")
    _fake_backend(monkeypatch, "webview.platforms.winforms", **attrs)
    assert "edgechromium" in selftest._window_problem()


def test_windows_missing_backend_fails(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _block_import(monkeypatch, "webview.platforms.winforms")
    assert "does not import" in selftest._window_problem()


def test_macos_cocoa_backend_passes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    _fake_backend(monkeypatch, "webview.platforms.cocoa")
    assert selftest._window_problem() is None


def test_macos_missing_backend_fails(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    _block_import(monkeypatch, "webview.platforms.cocoa")
    assert "webview.platforms.cocoa does not import" in selftest._window_problem()


def test_run_fails_fast_on_window_problem(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    _block_import(monkeypatch, "webview.platforms.cocoa")

    def never(*a, **k):
        raise AssertionError("the search must not start")
    monkeypatch.setattr(selftest, "_run", never)
    assert selftest.run() == 1
    out = capsys.readouterr().out.strip()
    assert out.startswith("SELFTEST FAIL window: ")
