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
    assert [0, 2, 1] in d["roads"]  # [x, y, level]
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
    imp = jobs.pop_improvement(jid)
    if imp is not None:
        assert isinstance(imp["stats"]["roads"], int)


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


def test_job_manager_submit_passes_concurrent_levels_through(monkeypatch):
    """concurrent_levels must reach RoadsFirstSearch -- the one lever this
    session's next-things-to-try sweep found to be a reproducible, no-downside
    speed win (tasks/lessons.md 2026-07-19/20), so production should be able
    to use it."""
    import webapp.runner as runner_mod
    captured = []

    class FakeSearch:
        def __init__(self, layout, **kwargs):
            captured.append(kwargs)

        def run(self, on_improvement=None, on_status=None, should_stop=None, **_kw):
            return {"verdict": "DONE", "results": {}}

    monkeypatch.setattr(runner_mod, "RoadsFirstSearch", FakeSearch)
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=1.0, patterns=5, probe_limit=1.0, workers=1,
                      concurrent_levels=4)
    for _ in range(300):
        if jobs.is_done(jid):
            break
        time.sleep(0.05)
    assert captured, "RoadsFirstSearch was never constructed"
    assert captured[0]["concurrent_levels"] == 4


def test_job_manager_submit_defaults_concurrent_levels_to_1(monkeypatch):
    """Omitting concurrent_levels must not silently change behavior for
    existing callers -- default stays 1, matching RoadsFirstSearch's own
    backward-compatible default."""
    import webapp.runner as runner_mod
    captured = []

    class FakeSearch:
        def __init__(self, layout, **kwargs):
            captured.append(kwargs)

        def run(self, on_improvement=None, on_status=None, should_stop=None, **_kw):
            return {"verdict": "DONE", "results": {}}

    monkeypatch.setattr(runner_mod, "RoadsFirstSearch", FakeSearch)
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=1.0, patterns=5, probe_limit=1.0, workers=1)
    for _ in range(300):
        if jobs.is_done(jid):
            break
        time.sleep(0.05)
    assert captured
    assert captured[0]["concurrent_levels"] == 1


def test_job_status_reports_phase_and_layouts_found(monkeypatch):
    import threading
    import webapp.runner as runner_mod
    release = threading.Event()

    class FakeSearch:
        def __init__(self, layout, **kwargs):
            pass

        def run(self, on_improvement=None, on_status=None, should_stop=None,
                on_phase=None, **_kw):
            on_phase("walk")
            release.wait(5)
            return {"verdict": "DONE", "results": {}}

    monkeypatch.setattr(runner_mod, "RoadsFirstSearch", FakeSearch)
    jobs = JobManager()
    jid = jobs.submit(_tiny_layout(), time_box=1.0, patterns=5, probe_limit=1.0, workers=1)
    assert jobs.status(jid)["phase"] in (None, "walk")
    for _ in range(200):
        if jobs.status(jid)["phase"] == "walk":
            break
        time.sleep(0.02)
    st = jobs.status(jid)
    release.set()
    assert st["phase"] == "walk" and st["layouts_found"] == 0


def _small_city():
    def b(eid, x, y, w, l, needs, th=False):
        return Building(eid, f"c{eid}", "main_building" if th else "g",
                        Footprint(x, y, w, l), needs, 1, th, None, None, f"a{eid}")
    th = b(1, 0, 0, 2, 2, False, True)
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    return Layout(region, [th, b(10, 0, 0, 2, 2, True), b(11, 0, 0, 2, 2, True),
                           b(12, 0, 0, 3, 2, True)], th, {})


def _run_to_end(jobs, jid):
    for _ in range(600):
        if jobs.is_done(jid):
            break
        time.sleep(0.05)
    assert jobs.snapshot(jid)["state"] == "done", jobs.snapshot(jid)["error"]
    return jobs.snapshot(jid)


def _drain(jobs, jid):
    out = []
    while (imp := jobs.pop_improvement(jid, timeout=0.05)) is not None:
        out.append(imp)
    return out


def test_run_result_keeps_every_legal_layout():
    jobs = JobManager()
    jid = jobs.submit(_small_city(), time_box=3.0, patterns=5, probe_limit=1.0,
                      workers=1)
    snap = _run_to_end(jobs, jid)
    imps = _drain(jobs, jid)
    layouts = snap["result"]["layouts"]
    assert imps and layouts
    assert snap["layouts_found"] >= len(layouts)
    for e in imps + layouts:
        assert isinstance(e["stats"]["roads"], int)
        assert e["legality"]["status"] == "valid"
    # the final best is among the kept layouts, and they are sorted by roads
    best = imps[-1]
    assert any(e["roads"] == best["roads"] and e["buildings"] == best["buildings"]
               for e in layouts)
    counts = [len(e["roads"]) for e in layouts]
    assert counts == sorted(counts) and counts[0] == len(best["roads"])


def test_run_with_off_road_publishes_valid_layouts():
    jobs = JobManager()
    jid = jobs.submit(_small_city(), time_box=3.0, patterns=5, probe_limit=1.0,
                      workers=1, off_road=frozenset({11}))
    snap = _run_to_end(jobs, jid)
    imps = _drain(jobs, jid)
    assert imps and snap["result"]["layouts"]
    for e in imps + snap["result"]["layouts"]:
        assert e["legality"]["status"] == "valid"
        # the off-road building keeps the player's road need in the stats
        assert e["stats"]["with_roads"] == 3


def test_stopped_run_still_has_layouts_key():
    jobs = JobManager()
    jid = jobs.submit(_small_city(), time_box=600.0, patterns=5, probe_limit=1.0,
                      workers=1)
    jobs.stop(jid)
    snap = _run_to_end(jobs, jid)
    assert "layouts" in snap["result"]


def test_seeded_input_city_is_not_offered_to_on_layout():
    from foeopt.roads_first import RoadsFirstSearch
    found = []
    RoadsFirstSearch(_small_city(), time_box=3.0, patterns=5, probe_limit=1.0,
                     workers=1).run(on_improvement=lambda lay, k, a: found.append(lay))
    # Every other publish site offers the layout to on_layout BEFORE
    # on_improvement, so a leading improvement with no offer is the seed.
    events = []
    RoadsFirstSearch(found[-1], time_box=2.0, patterns=5, probe_limit=1.0, workers=1,
                     seed_input=True).run(
        on_improvement=lambda lay, k, a: events.append(("improvement", a)),
        on_layout=lambda lay, k, a: events.append(("layout", a)))
    assert events[0] == ("improvement", len(found[-1].roads))
