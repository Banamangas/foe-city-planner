"""Position-indexed (symmetry-free) probe model, 2026-11-11."""
import random

import pytest

import foeopt.roads_first as rf
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import (generate_patterns, minimize_needed,
                                needed_skeleton_cells, prefilter, probe)

pytest.importorskip("ortools")


def _b(eid, w, l, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(0, 0, w, l), needs, 1, th, None, None, f"b{eid}")


def _legal(pat, region, consumers, pos):
    cells = []
    for b in consumers:
        x, y, w, l = pos[b.entity_id]
        assert (w, l) == (b.footprint.width, b.footprint.length)  # never rotated
        fp = Footprint(x, y, w, l)
        assert fp.cells() <= region
        assert not (fp.cells() & (set(pat.roads) | pat.th.cells()))
        assert fp.border_cells() & pat.roads           # road-adjacent
        cells += list(fp.cells())
    assert len(cells) == len(set(cells))               # no overlap


def test_position_and_item_models_agree_on_random_instances():
    """Same constraints, different encoding: wherever both decide, the verdict
    must match, and every position SAT must be a legal placement."""
    rng = random.Random(7)
    decided = agree = 0
    for trial in range(40):
        side = rng.randint(7, 10)
        region = {(x, y) for x in range(side) for y in range(side)}
        sizes = [rng.choice([(1, 1), (2, 2), (2, 1), (1, 2), (2, 3)]) for _ in range(rng.randint(3, 8))]
        consumers = [_b(10 + i, w, l) for i, (w, l) in enumerate(sizes)]
        pats = generate_patterns(region, 2, 2, rng.randint(4, 10), random.Random(trial), 10)
        pats = [p for p in pats if prefilter(p, region, consumers) is None]
        if not pats:
            continue
        pat = pats[0]
        si, pi = probe(pat, region, consumers, probe_limit=5.0)
        sp, pp = probe(pat, region, consumers, probe_limit=5.0, model="position")
        if sp == "SAT":
            _legal(pat, region, consumers, pp)
        if si != "UNKNOWN" and sp != "UNKNOWN":
            decided += 1
            agree += (si == sp)
    assert decided >= 20
    assert agree == decided


def test_position_identical_buildings_are_distinct_entities_in_the_answer():
    region = {(x, y) for x in range(8) for y in range(8)}
    consumers = [_b(10 + i, 2, 2) for i in range(4)]
    pat = next(p for p in generate_patterns(region, 2, 2, 6, random.Random(0), 30)
               if prefilter(p, region, consumers) is None)
    st, pos = probe(pat, region, consumers, probe_limit=5.0, model="position")
    if st == "SAT":
        assert sorted(pos) == [10, 11, 12, 13]
        _legal(pat, region, consumers, pos)


def _corridor():
    region = set((x, y) for x in range(12) for y in range(5))
    from foeopt.roads_first import Pattern
    return region, Pattern(th=Footprint(0, 1, 2, 2),
                           roads=frozenset((x, 2) for x in range(2, 12)), params={})


def test_position_objective_matches_the_item_objective():
    region, pat = _corridor()
    consumers = [_b(10 + i, 1, 1) for i in range(4)]
    far = {10: (11, 1, 1, 1), 11: (10, 1, 1, 1), 12: (11, 3, 1, 1), 13: (10, 3, 1, 1)}
    a = minimize_needed(pat, region, consumers, far, limit=5.0)
    b = minimize_needed(pat, region, consumers, far, limit=5.0, model="position")
    assert needed_skeleton_cells(pat, a) == needed_skeleton_cells(pat, b) == 2
    _legal(pat, region, consumers, b)


def test_search_rejects_unknown_probe_model():
    region, _ = _corridor()
    th = Building(1, "c1", "main_building", Footprint(0, 1, 2, 2), False, 1, True,
                  None, None, "TH")
    lay = Layout(Region(frozenset(region)), [th], th, {})
    with pytest.raises(ValueError):
        rf.RoadsFirstSearch(lay, time_box=5, probe_model="nope")


def test_seq_path_threads_probe_model_to_the_worker(monkeypatch):
    region, pat = _corridor()
    th = Building(1, "c1", "main_building", Footprint(0, 1, 2, 2), False, 1, True,
                  None, None, "TH")
    c = Building(10, "c10", "g", Footprint(2, 1, 1, 1), True, 1, False, None, None, "a")
    lay = Layout(Region(frozenset(region)), [th, c], th, {})
    seen = {}
    real = rf.probe

    def spy(*a, **k):
        seen["model"] = k.get("model")
        return real(*a, **k)

    monkeypatch.setattr(rf, "probe", spy)
    res = rf._run_probe_seq((pat, 10, lay, 5.0, 1, False, None, False, None, 0.0, 0.0,
                             None, "position"))
    assert seen["model"] == "position" and res["status"] == "SAT"
