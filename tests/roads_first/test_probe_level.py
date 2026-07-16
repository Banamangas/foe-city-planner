import random
import time
import pytest
from types import SimpleNamespace
from foeopt.model import Building, Footprint, Layout, Region
from foeopt import roads_first as mod


def test_probe_level_sequential_fallback_matches_today():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    call_order = []
    fake_layout = SimpleNamespace(roads=set(), buildings=[])

    def fake_run_probe(payload):
        pat, k, pat_index = payload
        call_order.append(pat.params)
        if len(call_order) == 1:
            return {"k": k, "params": pat.params, "status": "SAT",
                    "achieved": k, "secs": 0.1,
                    "layout": fake_layout, "pat_index": pat_index}
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.1, "layout": None,
                "pat_index": pat_index}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "_run_probe", fake_run_probe)

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    log_rows = []

    def log(row):
        log_rows.append(row)

    region_set = set(region.cells)
    rng = random.Random(0)
    try:
        status, best = mod._probe_level(lay, region_set, [c1], 1, rng,
                                        FakeArgs, log, pool=None)
    finally:
        monkeypatch.undo()

    pats = list(mod.generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    expected_order = [p.params for p in pats if mod.prefilter(p, region_set, [c1]) is None]
    assert call_order == expected_order
    assert status == "FEASIBLE"
    assert best == 1
    assert any(r.get("status") == "SAT" for r in log_rows)


def test_probe_level_defaults_to_comb_family(monkeypatch):
    """params without a pattern_family attribute (e.g. old callers/tests)
    must still dispatch to generate_patterns -- the comb family stays the
    default with zero behavior change."""
    calls = []
    real_comb = mod.generate_patterns
    def spy_comb(*a, **kw):
        calls.append("comb")
        return real_comb(*a, **kw)
    def spy_lane(*a, **kw):
        calls.append("lane")
        return []
    monkeypatch.setattr(mod, "generate_patterns", spy_comb)
    monkeypatch.setattr(mod, "generate_lane_patterns", spy_lane)

    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    mod._probe_level(lay, set(region.cells), [c1], 1, random.Random(0),
                     FakeArgs, lambda r: None, pool=None)
    assert calls == ["comb"]


def test_probe_level_pattern_family_lane_dispatches_to_lane_generator(monkeypatch):
    calls = []
    def spy_comb(*a, **kw):
        calls.append("comb")
        return []
    def spy_lane(*a, **kw):
        calls.append("lane")
        return []
    monkeypatch.setattr(mod, "generate_patterns", spy_comb)
    monkeypatch.setattr(mod, "generate_lane_patterns", spy_lane)

    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600
        pattern_family = "lane"

    mod._probe_level(lay, set(region.cells), [c1], 1, random.Random(0),
                     FakeArgs, lambda r: None, pool=None)
    assert calls == ["lane"]
