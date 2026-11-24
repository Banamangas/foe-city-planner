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
from logging.handlers import RotatingFileHandler

TITLE = "FoE City Planner"


def _setup_logging(folder: str) -> None:
    handler = RotatingFileHandler(os.path.join(folder, "app.log"),
                                  maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    from desktop import __version__
    from desktop.paths import data_dir

    parser = argparse.ArgumentParser(prog="foe-city-planner")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{TITLE} {__version__}")
        return 0

    folder = data_dir()
    _setup_logging(folder)
    log = logging.getLogger("desktop")

    if args.self_test:
        from desktop import selftest
        return selftest.run()

    try:
        from desktop import shell
        from webapp.app import create_app

        app = create_app(data_dir=folder)
        port = shell.free_port()
        shell.start_server(app, port)
        url = f"http://127.0.0.1:{port}/"
        log.info("serving on %s", url)
        try:
            if args.browser or not shell.run_window(url, shell.ShellApi(), TITLE):
                shell.run_browser(url, app)
        finally:
            shell.shutdown(app)
    except Exception:
        log.exception("the app stopped on an error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
