"""Plan N4 task 3: the desktop shell (server thread, idle exit, close prompt,
window-or-browser, headless self-test)."""
import builtins
import json
import socket
import threading
import time
import urllib.request

import pytest

from desktop import shell
from webapp.app import create_app


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


def test_shell_api_stores_running_state():
    api = shell.ShellApi()
    assert api.running is False
    api.set_running(True, "Quit?", "A search is running.")
    assert (api.running, api.title, api.message) == (True, "Quit?", "A search is running.")


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

    def start(**kw):
        raise RuntimeError("no GTK or Qt")
    fake.create_window = create_window
    fake.start = start
    monkeypatch.setitem(sys.modules, "webview", fake)
    assert shell.run_window("http://127.0.0.1:1/", shell.ShellApi(), "T") is False
    assert created["width"] == 1280 and created["height"] == 860
    assert created["min_size"] == (900, 640)


def test_close_prompt_only_while_running():
    asked = []

    class Win:
        def create_confirmation_dialog(self, title, message):
            asked.append((title, message))
            return False
    api = shell.ShellApi()
    handler = shell.closing_handler(Win(), api)
    assert handler() is True            # idle: close without asking
    assert asked == []
    api.set_running(True, "Quit?", "Search running")
    assert handler() is False           # declined: stay open
    assert asked == [("Quit?", "Search running")]


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
