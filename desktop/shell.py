"""The desktop shell: the local server, the app window (or the browser), the
close prompt during a search, and the idle exit of the browser mode."""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

log = logging.getLogger(__name__)

IDLE_TIMEOUT_S = 120.0
POLL_S = 5.0


def free_port() -> int:
    """A port free on 127.0.0.1 right now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bindable(port: int) -> bool:
    """Whether the server could bind `port` now. Like werkzeug, allow address
    reuse except on Windows (where it would let two servers share a port), so
    a port left in TIME_WAIT by the last run still counts as free."""
    with socket.socket() as s:
        if sys.platform != "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def remembered_port(data_dir: str) -> int | None:
    """The port in `<data_dir>/port.txt`, or None when missing or not a port."""
    try:
        with open(os.path.join(data_dir, "port.txt"), encoding="utf-8") as f:
            port = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return port if 1024 <= port <= 65535 else None


def preferred_port(data_dir: str) -> int:
    """The port remembered in `<data_dir>/port.txt` when it is free, else a
    free one (remembered for next time). The same port keeps the page's
    origin, so its saved settings (the language) survive a restart. Busy
    means another program holds it (a running copy of the app is caught
    first by `existing_instance`): take another for this run only."""
    remembered = remembered_port(data_dir)
    if remembered is not None:
        if _bindable(remembered):
            return remembered
        return free_port()   # busy for now: keep the remembered one
    port = free_port()
    path = os.path.join(data_dir, "port.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(port))
    except OSError:
        log.warning("could not remember the port in %s", path, exc_info=True)
    return port


def existing_instance(port: int, timeout: float = 1.0) -> bool:
    """Whether a copy of the desktop app already serves on `port`: its
    `GET /api/session` answers 200 JSON, or 404 with exactly
    {"error": "no session"} (the developer server and other programs don't)."""
    url = f"http://127.0.0.1:{port}/api/session"
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
    try:
        try:
            with direct.open(url, timeout=timeout) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        body = json.loads(raw)
    except Exception:  # anything that isn't a clean answer: not our app
        return False
    if not isinstance(body, dict):
        return False
    if status == 200:
        return True
    return status == 404 and body == {"error": "no session"}


def start_server(app, port: int) -> threading.Thread:
    """Serve `app` on 127.0.0.1:`port` from a daemon thread; return once the
    port accepts connections (up to 10 s). The app learns its port (for the
    desktop mode's Host check). The thread carries the server as
    `.server` so `stop_server` can shut it down."""
    from werkzeug.serving import make_server
    app.config["FOEOPT_PORT"] = port   # the host guard accepts only this port
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, name="foeopt-server", daemon=True)
    thread.server = server
    thread.start()
    deadline = time.monotonic() + 10.0
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return thread
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError(f"the local server did not start on port {port}")
            time.sleep(0.05)


def stop_server(thread: threading.Thread) -> None:
    thread.server.shutdown()
    thread.server.server_close()


def confirm_needed(running: bool) -> bool:
    """Closing asks first only while a search runs."""
    return running


def should_exit(last_ping: float, now: float, job_running: bool,
                timeout: float = IDLE_TIMEOUT_S) -> bool:
    """Browser mode: quit when no page has pinged for `timeout` seconds and no
    search runs. The caller passes the start time until the first ping."""
    if job_running:
        return False
    return now - last_ping > timeout


def shutdown(app, wait_s: float = 5.0) -> None:
    """Stop every search and wait (up to `wait_s`) for them to end."""
    jobs = app.extensions["foeopt_jobs"]
    jobs.stop_all()
    deadline = time.monotonic() + wait_s
    while jobs.any_running() and time.monotonic() < deadline:
        time.sleep(0.05)


class ShellApi:
    """Exposed to the page as `window.pywebview.api` (pywebview skips names
    starting with "_", so the window stays private). The page reports when a
    search starts or ends, with the close-prompt texts in its language; they
    drive pywebview's built-in close confirmation, which runs inline on the GUI
    thread (a dialog opened from a `closing` handler deadlocks on macOS)."""

    def __init__(self) -> None:
        self.running = False
        self.title = ""
        self.message = ""
        self._labels: dict[str, str] = {}
        self._window = None

    def _attach(self, window) -> None:
        self._window = window
        self._apply()

    def set_running(self, running, title, message, quit_label=None, cancel_label=None):
        self.running = bool(running)
        self.title = str(title or "")
        self.message = str(message or "")
        if quit_label:
            self._labels["global.quit"] = str(quit_label)
        if cancel_label:
            self._labels["global.cancel"] = str(cancel_label)
        self._apply()

    def _apply(self) -> None:
        window = self._window
        if window is None:
            return
        window.confirm_close = confirm_needed(self.running)
        texts = dict(self._labels)
        if self.message:
            texts["global.quitConfirmation"] = self.message
        # In place: the GUI backend holds a reference to this very dict. Before
        # webview.start() only the override exists (start copies it in).
        for name in ("localization", "localization_override"):
            loc = getattr(window, name, None)
            if isinstance(loc, dict):
                loc.update(texts)


def _windows_renderer_ok() -> bool:
    """On Windows, pywebview falls back to the old MSHTML engine (a blank
    window for this app) when the WebView2 runtime is missing; the browser is
    better then. Importing the backend only reads which engine it found."""
    if sys.platform != "win32":
        return True
    import importlib
    return getattr(importlib.import_module("webview.platforms.winforms"),
                   "renderer", None) == "edgechromium"


def run_window(url: str, api: ShellApi, title: str, storage_dir: str | None = None) -> bool:
    """Show the app in its own window until it closes (True). False when
    pywebview is missing or no GUI can start: the caller opens the browser.
    The page's storage persists in `storage_dir` (default <data dir>/webview)."""
    shown = threading.Event()
    try:
        import webview
        if not _windows_renderer_ok():
            log.info("no WebView2 runtime, using the browser")
            return False
        if storage_dir is None:
            from desktop.paths import data_dir
            storage_dir = os.path.join(data_dir(), "webview")
        window = webview.create_window(title, url, js_api=api, width=1280, height=860,
                                       min_size=(900, 640), localization={})
        api._attach(window)
        window.events.shown += shown.set
        webview.start(private_mode=False, storage_path=storage_dir)
    except Exception:
        if shown.is_set():
            log.exception("the window failed after it opened")
            return True
        log.info("no app window available, using the browser", exc_info=True)
        return False
    return True


def run_browser(url: str, app, *, poll_s: float = POLL_S,
                timeout: float = IDLE_TIMEOUT_S) -> None:
    """Open the default browser and return once the page is gone (no ping for
    `timeout` seconds) and no search runs."""
    started = time.monotonic()
    webbrowser.open(url)
    jobs = app.extensions["foeopt_jobs"]
    while True:
        time.sleep(poll_s)
        last = app.config.get("LAST_PING") or started
        if should_exit(last, time.monotonic(), jobs.any_running(), timeout):
            return
