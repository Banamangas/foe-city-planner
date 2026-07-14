import pytest
from foeopt.model import Building, Footprint, Layout, Region
from foeopt import roads_first as mod


def test_run_probe_unsat_returns_status_no_layout(monkeypatch):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 1, 1),
                  False, 1, True, None, None, "TH")
    consumer = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(2) for y in range(2)))
    lay = Layout(region, [th, consumer], th, {})

    import random
    pats = list(mod.generate_patterns(set(region.cells), 1, 1, 1, random.Random(0), 5))
    assert pats
    pat = pats[0]

    def fake_probe(pattern, region, consumers, *, probe_limit, **kwargs):
        return ("UNSAT", None)

    monkeypatch.setattr(mod, "probe", fake_probe)
    mod._WORKER_LAYOUT = lay
    mod._WORKER_PROBE_LIMIT = 30.0
    mod._WORKER_PROBE_WORKERS = 1
    try:
        result = mod._run_probe((pat, 1, 0))
    finally:
        mod._WORKER_LAYOUT = None
    assert set(result.keys()) >= {"k", "params", "status", "achieved", "secs", "layout"}
    assert result["status"] == "UNSAT"
    assert result["achieved"] is None
    assert result["layout"] is None
    assert isinstance(result["secs"], float)
    assert result["secs"] >= 0.0
    assert result["k"] == 1
    assert result["params"] == pat.params


def test_run_probe_payload_uses_worker_global_not_embedded_layout(monkeypatch):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    import random
    mod._WORKER_LAYOUT = lay
    mod._WORKER_PROBE_LIMIT = 30.0
    mod._WORKER_PROBE_WORKERS = 1
    try:
        pats = list(mod.generate_patterns(set(region.cells), 2, 2, 1, random.Random(0), 5))
        pat = next(p for p in pats if mod.prefilter(p, set(region.cells), [c1]) is None)
        monkeypatch.setattr(mod, "probe",
                            lambda pattern, region, consumers, *, probe_limit, probe_workers=1:
                            ("UNSAT", None))
        result = mod._run_probe((pat, 1, 0))
        assert result["pat_index"] == 0
        assert result["k"] == 1
    finally:
        mod._WORKER_LAYOUT = None
        del mod._WORKER_PROBE_LIMIT
        del mod._WORKER_PROBE_WORKERS
