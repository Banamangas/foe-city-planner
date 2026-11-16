"""scripts/bench.py: arm parsing, preset translation, verdict, machine lock."""
import importlib.util
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bench", ROOT / "scripts" / "bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_parse_arm():
    assert bench.parse_arm("preset") == ("preset", {})
    name, over = bench.parse_arm('x:probe_limit=10; road_witness=false;pattern_family=lane;band=[3,4]')
    assert name == "x"
    assert over == {"probe_limit": 10, "road_witness": False,
                    "pattern_family": "lane", "band": [3, 4]}
    with pytest.raises(SystemExit):
        bench.parse_arm("x:novalue")


def test_search_kwargs_translates_preset():
    kw = bench.search_kwargs({}, 120.0)
    assert kw["time_box"] == 120.0
    assert kw["quality_index_band"] == (3, 4)
    assert kw["comb_modes"] == ("alternate",)
    assert kw["workers"] == 6 and kw["probe_workers"] == 2
    kw = bench.search_kwargs({"quality_index_band": "", "workers": 8}, 5)
    assert kw["quality_index_band"] is None and kw["workers"] == 8


def _row(arm, city, rep, best, accepted=True, box=120.0):
    return {"arm": arm, "city": city, "box": box, "rep": rep, "ok": True,
            "best": best, "accepted": accepted}


def test_report_verdicts():
    rows = [_row("base", "a", 0, 90), _row("new", "a", 0, 88),
            _row("base", "a", 1, 90), _row("new", "a", 1, 90),
            _row("base", "b", 0, None), _row("new", "b", 0, 70)]
    assert "new vs base: better 2, worse 0, tie 1 -> ADOPT" in bench.report(rows, "base")
    rows.append(_row("base", "c", 0, 50))
    rows.append(_row("new", "c", 0, 49, accepted=False))  # failed verify = no result
    assert "-> REJECT" in bench.report(rows, "base")


def test_lock_blocks_second_holder(tmp_path, monkeypatch):
    lock = tmp_path / ".lock"
    monkeypatch.setattr(bench, "LOCK", lock)
    holder = subprocess.Popen([sys.executable, "-c", f"""
import fcntl, time
fh = open({str(lock)!r}, 'a+'); fcntl.flock(fh, fcntl.LOCK_EX)
fh.write('other'); fh.flush(); print('locked', flush=True); time.sleep(30)
"""], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(SystemExit, match="held by"):
            with bench.machine_lock(wait=False, label="t"):
                pass
    finally:
        holder.kill()
        holder.wait()
    with bench.machine_lock(wait=False, label="t"):   # free again
        assert "pid=" in lock.read_text()
