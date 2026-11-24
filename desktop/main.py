"""Entry point of the desktop app (and of its frozen builds).

Starts the local server on 127.0.0.1, shows the app in its own window (or the
default browser), and stops every search on the way out. Errors go to
<data dir>/app.log, never to the player."""
from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler

TITLE = "FoE City Planner"


_log_handler: logging.Handler | None = None


def _setup_logging(folder: str) -> None:
    """app.log in `folder` (1 MB, 1 backup); nothing at all if it can't be
    written, since a windowed build has no console to fall back on."""
    global _log_handler
    root = logging.getLogger()
    if _log_handler is not None:
        root.removeHandler(_log_handler)
        _log_handler.close()
    try:
        handler = RotatingFileHandler(os.path.join(folder, "app.log"), maxBytes=1_000_000,
                                      backupCount=1, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _log_handler = handler
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # no line per request


def _folder() -> str:
    """The data folder, or a temp folder when it can't be created."""
    from desktop import paths
    try:
        return paths.data_dir()
    except OSError:
        folder = os.path.join(tempfile.gettempdir(), "foe-city-planner")
        os.makedirs(folder, exist_ok=True)
        return folder


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    from desktop import __version__

    parser = argparse.ArgumentParser(prog="foe-city-planner")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{TITLE} {__version__}")
        return 0

    log = logging.getLogger("desktop")
    try:
        folder = _folder()
        _setup_logging(folder)
    except Exception:
        folder = None

    if args.self_test:
        from desktop import selftest
        return selftest.run()

    try:
        from desktop import shell
        from webapp.app import create_app

        if folder is None:
            raise RuntimeError("no folder to keep the city in")
        app = create_app(data_dir=folder)
        port = shell.preferred_port(folder)
        try:
            shell.start_server(app, port)
        except OSError:          # taken between the check and the bind
            port = shell.free_port()
            shell.start_server(app, port)
        url = f"http://127.0.0.1:{port}/"
        log.info("serving on %s", url)
        # The Linux build runs in the default browser (no window toolkit to rely on).
        use_browser = args.browser or sys.platform.startswith("linux")
        try:
            if use_browser or not shell.run_window(
                    url, shell.ShellApi(), TITLE, os.path.join(folder, "webview")):
                shell.run_browser(url, app)
        finally:
            shell.shutdown(app)
    except KeyboardInterrupt:
        return 0
    except Exception:
        log.exception("the app stopped on an error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
