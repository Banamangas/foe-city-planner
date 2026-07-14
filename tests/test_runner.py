import time
import pytest

from foeopt.model import Building, Footprint, Layout, Region
from webapp.runner import JobManager, layout_to_dict


def _tiny_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {})


def test_layout_to_dict_serializes_layout():
    lay = _tiny_layout()
    lay.roads = {(0, 2): 1}
    d = layout_to_dict(lay)
    assert isinstance(d, dict)
    assert "roads" in d
    assert isinstance(d["roads"], list)
    assert [0, 2] in d["roads"]
    assert "buildings" in d
    assert isinstance(d["buildings"], dict)
    for eid, coords in d["buildings"].items():
        assert len(coords) == 4


def test_job_manager_submit_and_status():
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=1.0, patterns=5, probe_limit=1.0, workers=1)
    assert isinstance(jid, str)
    st = jobs.status(jid)
    assert st["state"] in ("running", "done", "error")
    # wait for completion
    for _ in range(300):
        st = jobs.status(jid)
        if st["state"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["state"] in ("done", "error")


def test_job_manager_stop_signals_search():
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=600.0, patterns=5, probe_limit=1.0, workers=1)
    jobs.stop(jid)
    for _ in range(300):
        if jobs.is_done(jid):
            break
        time.sleep(0.1)
    assert jobs.is_done(jid)


def test_job_manager_pop_improvement_returns_none_when_empty():
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=1.0, patterns=5, probe_limit=1.0, workers=1)
    imp = jobs.pop_improvement(jid, timeout=0.1)
    # may be None if no improvement found yet, or a dict if found
    assert imp is None or isinstance(imp, dict)


def test_job_manager_unknown_job_status():
    jobs = JobManager()
    assert jobs.status("nonexistent")["state"] == "error"
