"""Plan N4 task 3: the desktop shell (server thread, idle exit, close prompt,
window-or-browser, headless self-test)."""
import builtins
import json
import os
import socket
import threading
import time
import urllib.request

import pytest

from desktop import shell
from webapp.app import create_app


@pytest.fixture(autouse=True)
def _restore_logging():
    """main() adds a file handler to the root logger: take it off again."""
    import logging
    root = logging.getLogger()
    level, werkzeug_level = root.level, logging.getLogger("werkzeug").level
    yield
    from desktop import main as main_mod
    if main_mod._log_handler is not None:
        root.removeHandler(main_mod._log_handler)
        main_mod._log_handler.close()
        main_mod._log_handler = None
    root.setLevel(level)
    logging.getLogger("werkzeug").setLevel(werkzeug_level)


def test_free_port_gives_bindable_ports():
    ports = [shell.free_port(), shell.free_port()]
    for p in ports:
        assert isinstance(p, int) and 1024 <= p <= 65535
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
        finally:
            s.close()


def test_should_exit():
    assert shell.should_exit(0.0, 121.0, job_running=False) is True   # start=0, no ping
    assert shell.should_exit(100.0, 121.0, job_running=False) is False
    assert shell.should_exit(0.0, 500.0, job_running=True) is False


def test_confirm_needed():
    assert shell.confirm_needed(True) is True
    assert shell.confirm_needed(False) is False


class _FakeWindow:
    def __init__(self):
        self.confirm_close = False
        self.localization = {"global.quitConfirmation": "Do you want to quit?",
                             "global.quit": "Quit", "global.cancel": "Cancel"}


def test_shell_api_stores_running_state():
    api = shell.ShellApi()
    assert api.running is False
    api.set_running(True, "Quit?", "A search is running.")   # no window yet: no error
    assert (api.running, api.title, api.message) == (True, "Quit?", "A search is running.")


def test_set_running_drives_builtin_close_confirmation():
    api = shell.ShellApi()
    win = _FakeWindow()
    loc = win.localization
    api._attach(win)
    api.set_running(True, "T", "Search running", "Close anyway", "Keep searching")
    assert win.confirm_close is True
    assert win.localization is loc          # updated in place (the GUI holds this dict)
    assert loc["global.quitConfirmation"] == "Search running"
    assert loc["global.quit"] == "Close anyway"
    assert loc["global.cancel"] == "Keep searching"
    api.set_running(False, "", "")
    assert win.confirm_close is False
    assert loc["global.quit"] == "Close anyway"   # empty labels leave them alone


def test_attach_applies_state_set_before_the_window():
    api = shell.ShellApi()
    api.set_running(True, "T", "M")
    win = _FakeWindow()
    api._attach(win)
    assert win.confirm_close is True
    assert win.localization["global.quitConfirmation"] == "M"


def test_window_is_not_exposed_to_the_page():
    api = shell.ShellApi()
    api._attach(_FakeWindow())
    # pywebview exposes every public name of the js_api object to the page
    assert {n for n in dir(api) if not n.startswith("_")} == {
        "running", "title", "message", "set_running"}


def test_preferred_port_is_remembered(tmp_path):
    p1 = shell.preferred_port(str(tmp_path))
    assert (tmp_path / "port.txt").read_text().strip() == str(p1)
    assert shell.preferred_port(str(tmp_path)) == p1


def test_preferred_port_busy_takes_another(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    busy = s.getsockname()[1]
    try:
        (tmp_path / "port.txt").write_text(str(busy))
        p = shell.preferred_port(str(tmp_path))
        assert p != busy and 1024 <= p <= 65535
        # busy only for this run (a second copy): keep the remembered port
        assert (tmp_path / "port.txt").read_text() == str(busy)
    finally:
        s.close()


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="no TIME_WAIT reuse rule")
def test_port_in_time_wait_is_still_usable():
    """Closing the app leaves its port in TIME_WAIT; werkzeug binds it anyway
    (SO_REUSEADDR), so a quick relaunch must keep the remembered port."""
    lsock = socket.socket()
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # as werkzeug's server does
    lsock.bind(("127.0.0.1", 0))
    lsock.listen()
    port = lsock.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = lsock.accept()
    conn.close()          # the server side closes first: its port enters TIME_WAIT
    time.sleep(0.05)
    client.close()
    lsock.close()
    plain = socket.socket()
    try:
        with pytest.raises(OSError):
            plain.bind(("127.0.0.1", port))   # the bug: a plain bind says busy
    finally:
        plain.close()
    assert shell._bindable(port) is True


def test_preferred_port_corrupt_file(tmp_path):
    (tmp_path / "port.txt").write_text("not a port")
    p = shell.preferred_port(str(tmp_path))
    assert 1024 <= p <= 65535
    (tmp_path / "port.txt").write_text("99999")
    assert 1024 <= shell.preferred_port(str(tmp_path)) <= 65535


def test_shutdown_stops_running_job(tmp_path):
    app = create_app(data_dir=str(tmp_path))
    jobs = app.extensions["foeopt_jobs"]
    stopped = threading.Event()
    state = {"state": "running", "start": time.monotonic(), "end": None}
    stop_event = threading.Event()
    jobs._jobs["fake"] = {"state": state, "stop_event": stop_event}

    def finisher():
        stop_event.wait(5)
        stopped.set()
        state["state"] = "done"
    threading.Thread(target=finisher, daemon=True).start()

    t0 = time.monotonic()
    shell.shutdown(app)
    assert time.monotonic() - t0 < 1.0
    assert stopped.is_set()
    assert jobs.any_running() is False


def test_start_server_serves_on_localhost(tmp_path):
    app = create_app(data_dir=str(tmp_path))
    port = shell.free_port()
    thread = shell.start_server(app, port)
    assert thread.daemon
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/options", timeout=10) as r:
        assert r.status == 200
        assert "presets" in json.loads(r.read())
    shell.stop_server(thread)


def test_run_window_falls_back_without_pywebview(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "webview" or name.startswith("webview."):
            raise ImportError("no webview")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert shell.run_window("http://127.0.0.1:1/", shell.ShellApi(), "FoE City Planner") is False


def test_run_window_falls_back_when_gui_cannot_start(monkeypatch):
    import sys
    import types

    class Ev:
        def __init__(self):
            self.items = []

        def __iadd__(self, f):
            self.items.append(f)
            return self

    class Win:
        def __init__(self):
            self.events = types.SimpleNamespace(closing=Ev(), shown=Ev())

    fake = types.ModuleType("webview")
    created = {}

    def create_window(title, url, **kw):
        created.update(kw, title=title, url=url)
        return Win()

    started = {}

    def start(**kw):
        started.update(kw)
        raise RuntimeError("no GTK or Qt")
    fake.create_window = create_window
    fake.start = start
    monkeypatch.setitem(sys.modules, "webview", fake)
    assert shell.run_window("http://127.0.0.1:1/", shell.ShellApi(), "T",
                            storage_dir="/x/webview") is False
    assert started["private_mode"] is False and started["storage_path"] == "/x/webview"
    assert created["width"] == 1280 and created["height"] == 860
    assert created["min_size"] == (900, 640)


def test_run_window_refuses_mshtml_on_windows(monkeypatch):
    import sys
    import types
    fake = types.ModuleType("webview")
    calls = []
    fake.create_window = lambda *a, **k: calls.append("create")
    fake.start = lambda **k: calls.append("start")
    winforms = types.ModuleType("webview.platforms.winforms")
    winforms.renderer = "mshtml"
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", winforms)
    monkeypatch.setattr(sys, "platform", "win32")
    assert shell.run_window("http://127.0.0.1:1/", shell.ShellApi(), "T") is False
    assert calls == []


def _fake_shell(monkeypatch, calls, browser_exc=None):
    monkeypatch.setattr(shell, "start_server", lambda app, port: calls.append("server"))
    monkeypatch.setattr(shell, "run_window",
                        lambda *a, **k: calls.append("window") or True)

    def run_browser(url, app):
        calls.append("browser")
        if browser_exc:
            raise browser_exc
    monkeypatch.setattr(shell, "run_browser", run_browser)
    monkeypatch.setattr(shell, "shutdown", lambda app: calls.append("shutdown"))


def test_main_uses_browser_on_linux(monkeypatch, tmp_path):
    import sys
    from desktop.main import main
    monkeypatch.setenv("FOEOPT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    calls = []
    _fake_shell(monkeypatch, calls)
    assert main([]) == 0
    assert calls == ["server", "browser", "shutdown"]
    import logging
    assert logging.getLogger("werkzeug").level == logging.WARNING


def test_main_ctrl_c_exits_cleanly(monkeypatch, tmp_path):
    from desktop.main import main
    monkeypatch.setenv("FOEOPT_DATA_DIR", str(tmp_path))
    calls = []
    _fake_shell(monkeypatch, calls, browser_exc=KeyboardInterrupt())
    assert main(["--browser"]) == 0
    assert calls[-1] == "shutdown"


def test_main_survives_unusable_data_dir(monkeypatch):
    import desktop.paths
    from desktop import main as main_mod, selftest

    def broken():
        raise PermissionError("read-only")
    monkeypatch.setattr(desktop.paths, "data_dir", broken)
    monkeypatch.setattr(selftest, "run", lambda: 0)
    assert main_mod.main(["--self-test"]) == 0


def test_selftest_restores_update_env(monkeypatch):
    from desktop import selftest
    monkeypatch.delenv("FOEOPT_NO_UPDATE", raising=False)
    seen = []

    def check(base, deadline):
        seen.append(os.environ.get("FOEOPT_NO_UPDATE"))
        raise selftest._Fail("stubbed")
    monkeypatch.setattr(selftest, "_check", check)
    assert selftest.run() == 1
    assert seen == ["1"]
    assert "FOEOPT_NO_UPDATE" not in os.environ


def test_main_version(capsys):
    from desktop.main import main
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip()


@pytest.mark.slow
def test_selftest_runs_real_optimizer(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("FOEOPT_DATA_DIR", str(tmp_path))
    from desktop import selftest
    assert selftest.run() == 0
    out = capsys.readouterr().out
    assert "SELFTEST OK roads=" in out
