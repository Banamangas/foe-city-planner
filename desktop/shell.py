"""The desktop shell: the local server, the app window (or the browser), the
close prompt during a search, and the idle exit of the browser mode."""
from __future__ import annotations

import logging
import socket
import threading
import time
import webbrowser

log = logging.getLogger(__name__)

IDLE_TIMEOUT_S = 120.0
POLL_S = 5.0


def free_port() -> int:
    """A port free on 127.0.0.1 right now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(app, port: int) -> threading.Thread:
    """Serve `app` on 127.0.0.1:`port` from a daemon thread; return once the
    port accepts connections (up to 10 s). The thread carries the server as
    `.server` so `stop_server` can shut it down."""
    from werkzeug.serving import make_server
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


def should_exit(last_ping: float | None, now: float, job_running: bool,
                timeout: float = IDLE_TIMEOUT_S) -> bool:
    """Browser mode: quit when no page has pinged for `timeout` seconds and no
    search runs. The caller passes the start time until the first ping."""
    if job_running:
        return False
    return now - (last_ping or 0.0) > timeout


def shutdown(app, wait_s: float = 5.0) -> None:
    """Stop every search and wait (up to `wait_s`) for them to end."""
    jobs = app.extensions["foeopt_jobs"]
    jobs.stop_all()
    deadline = time.monotonic() + wait_s
    while jobs.any_running() and time.monotonic() < deadline:
        time.sleep(0.05)


class ShellApi:
    """Exposed to the page as `window.pywebview.api`. The page reports when a
    search starts or ends, with the close-prompt texts in its language."""

    def __init__(self) -> None:
        self.running = False
        self.title = ""
        self.message = ""

    def set_running(self, running, title, message):
        self.running = bool(running)
        self.title = str(title or "")
        self.message = str(message or "")


def closing_handler(window, api: ShellApi):
    """The window's `closing` handler: False keeps the window open."""
    def on_closing():
        if not confirm_needed(api.running):
            return True
        return bool(window.create_confirmation_dialog(api.title, api.message))
    return on_closing


def run_window(url: str, api: ShellApi, title: str) -> bool:
    """Show the app in its own window until it closes (True). False when
    pywebview is missing or no GUI can start: the caller opens the browser."""
    shown = threading.Event()
    try:
        import webview
        window = webview.create_window(title, url, js_api=api, width=1280, height=860,
                                       min_size=(900, 640))
        window.events.closing += closing_handler(window, api)
        window.events.shown += shown.set
        webview.start()
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
