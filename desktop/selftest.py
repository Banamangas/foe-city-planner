"""Headless self-test of a build: a real 20 s search on a synthetic city plus
an export, all over HTTP against the local server, no window.

Prints one line, `SELFTEST OK roads=<before>-><best> layouts=<n>` (exit 0) or
`SELFTEST FAIL <reason>` (exit 1)."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_CITY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest_city.json")


class _Fail(Exception):
    pass


def _post(base: str, path: str, body: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post_json(base: str, path: str, body: dict, timeout: float = 60.0) -> dict:
    status, raw = _post(base, path, body, timeout)
    if status != 200:
        raise _Fail(f"{path} answered {status}: {raw[:200]!r}")
    return json.loads(raw)


def _read_done(base: str, job_id: str, deadline: float) -> dict:
    """Read the event stream until the `done` event; return its data."""
    timeout = max(1.0, deadline - time.monotonic())
    with urllib.request.urlopen(f"{base}/api/stream/{job_id}", timeout=timeout) as r:
        event = None
        for raw in r:
            if time.monotonic() > deadline:
                raise _Fail("the search did not finish in time")
            line = raw.decode().rstrip("\r\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "done":
                return json.loads(line[6:])
    raise _Fail("the stream ended without a done event")


def _check(base: str, deadline: float) -> str:
    with open(_CITY, encoding="utf-8") as f:
        city = json.load(f)
    loaded = _post_json(base, "/api/load?lang=en", city)
    before = loaded["stats"]["roads"]
    with urllib.request.urlopen(f"{base}/api/options", timeout=30) as r:
        best = json.loads(r.read())["presets"]["best"]
    started = _post_json(base, "/api/optimize",
                         {**best, "city_id": loaded["city_id"], "time_box": 20})
    done = _read_done(base, started["job_id"], deadline)
    if done.get("state") != "done":
        raise _Fail(f"the search ended in state {done.get('state')}: {done.get('error')}")
    layouts = (done.get("result") or {}).get("layouts") or []
    if not layouts:
        raise _Fail("no layout found")
    top = layouts[0]
    status, raw = _post(base, "/api/export/v3",
                        {"city_id": loaded["city_id"], "layout": top}, 60.0)
    if status != 200:
        raise _Fail(f"export answered {status}: {raw[:200]!r}")
    if not isinstance(json.loads(raw).get("cityData"), dict):
        raise _Fail("export has no cityData")
    return f"roads={before}->{len(top['roads'])} layouts={len(layouts)}"


def _say(line: str) -> None:
    """The result line, on stdout and in the log (a windowed build has no
    console)."""
    print(line, flush=True)
    log.info(line)


def run(timeout_s: float = 240.0) -> int:
    os.environ["FOEOPT_NO_UPDATE"] = "1"   # never download during the test
    from desktop import shell
    from webapp.app import create_app

    deadline = time.monotonic() + timeout_s
    with tempfile.TemporaryDirectory(prefix="foeopt-selftest-",
                                     ignore_cleanup_errors=True) as tmp:
        app = None
        server = None
        try:
            app = create_app(data_dir=tmp)
            port = shell.free_port()
            server = shell.start_server(app, port)
            summary = _check(f"http://127.0.0.1:{port}", deadline)
        except Exception as exc:
            reason = str(exc) if isinstance(exc, _Fail) else f"{type(exc).__name__}: {exc}"
            log.exception("self-test failed")
            _say(f"SELFTEST FAIL {reason}")
            return 1
        finally:
            if app is not None:
                shell.shutdown(app)
            if server is not None:
                shell.stop_server(server)
    _say(f"SELFTEST OK {summary}")
    return 0
