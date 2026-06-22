import time
from foeopt.model import Building, Footprint, Layout, Region
from webapp.runner import run_repack, JobManager


def _sparse_city():
    th = Building(1, "c1", "t", Footprint(0, 0, 2, 2), False, 0, True, None, None, "TH")
    cons = [Building(10 + i, f"c{i}", "t", Footprint(0, 0, 2, 2), True, 1, False, None, None, f"r{i}")
            for i in range(3)]
    region = Region(frozenset({(x, y) for x in range(20) for y in range(20)}))
    return Layout(region, [th, *cons], th)


def test_run_repack_returns_result_dict():
    res = run_repack(_sparse_city(), budget=2.0, seed=0)
    assert res["placed"] == 4 and res["unplaced"] == 0
    assert isinstance(res["roads"], int) and isinstance(res["estimate"], int)
    assert res["valid"] is True
    assert "<svg" in res["map_html"] or "<html" in res["map_html"]


def test_jobmanager_runs_and_reports():
    jm = JobManager()
    jid = jm.submit(lambda: {"ok": 1})
    for _ in range(50):
        st = jm.status(jid)
        if st["state"] == "done":
            break
        time.sleep(0.02)
    assert st["state"] == "done" and st["result"] == {"ok": 1}
    assert st["elapsed"] >= 0


def test_run_repack_polish_not_worse_and_reports_base():
    from webapp.runner import run_repack
    res = run_repack(_sparse_city(), budget=0.3, seed=0, anneal_budget=0.4)
    assert res["unplaced"] == 0 and res["valid"] is True
    assert "base_roads" in res
    assert res["roads"] <= res["base_roads"]   # anneal never worse


def test_jobmanager_reports_error():
    jm = JobManager()
    def boom():
        raise RuntimeError("nope")
    jid = jm.submit(boom)
    for _ in range(50):
        st = jm.status(jid)
        if st["state"] == "error":
            break
        time.sleep(0.02)
    assert st["state"] == "error" and "nope" in st["error"]
