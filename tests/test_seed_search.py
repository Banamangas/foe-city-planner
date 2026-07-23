import random

import pytest

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern, generate_patterns, prefilter
from foeopt import seed_search


def _toy():
    """6x6 region, TH + one road-needing consumer -- probe finds SAT quickly."""
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {})


# --- aggregation logic (seam: _solve_one monkeypatched, no solver) ---------

def test_keeps_minimum_achieved_across_seeds(monkeypatch):
    """probe() has no objective, so achieved varies by solver seed. The result
    must be the LOWEST legal achieved, and must report which seed produced it."""
    layout, pat = _toy(), Pattern(Footprint(0, 0, 2, 2), frozenset({(0, 2)}), {})
    scripted = {0: (105, "L105"), 1: (98, "L98"), 2: (101, "L101")}

    def fake_solve(lay, p, seed, **kw):
        ach, tag = scripted[seed]
        return ach, tag

    monkeypatch.setattr(seed_search, "_solve_one", fake_solve)
    res = seed_search.seed_minimize_roads(layout, pat, seeds=range(3),
                                          probe_limit=1.0)
    assert res.achieved == 98
    assert res.seed == 1
    assert res.layout == "L98"
    assert res.n_legal == 3
    assert res.n_tried == 3


def test_infeasible_seeds_do_not_count_and_yield_no_layout(monkeypatch):
    """Seeds that don't produce a legal validated layout return None from
    _solve_one and must be skipped, not crash or count as legal."""
    layout, pat = _toy(), Pattern(Footprint(0, 0, 2, 2), frozenset({(0, 2)}), {})
    monkeypatch.setattr(seed_search, "_solve_one", lambda *a, **k: None)
    res = seed_search.seed_minimize_roads(layout, pat, seeds=range(4),
                                          probe_limit=1.0)
    assert res.achieved is None
    assert res.layout is None
    assert res.seed is None
    assert res.n_legal == 0
    assert res.n_tried == 4


def test_first_seed_wins_ties(monkeypatch):
    """On a tie the earliest seed wins -- deterministic, reproducible result."""
    layout, pat = _toy(), Pattern(Footprint(0, 0, 2, 2), frozenset({(0, 2)}), {})
    scripted = {7: (100, "A"), 3: (100, "B"), 9: (100, "C")}
    monkeypatch.setattr(seed_search, "_solve_one",
                        lambda lay, p, seed, **k: scripted[seed])
    res = seed_search.seed_minimize_roads(layout, pat, seeds=[7, 3, 9],
                                          probe_limit=1.0)
    assert res.achieved == 100 and res.seed == 7 and res.layout == "A"


# --- _solve_one legality gate (the retracted-record failure mode) ----------

def test_solve_one_rejects_rotated_placement(monkeypatch):
    """A placement whose buildings are rotated (w/l swapped) is illegal in FoE
    and must never be returned, even if probe/validate accepted it."""
    layout, pat = _toy(), Pattern(Footprint(0, 0, 2, 2), frozenset({(0, 2)}), {})
    monkeypatch.setattr(seed_search, "probe", lambda *a, **k: ("SAT", {}))
    monkeypatch.setattr(seed_search, "validate",
                        lambda *a, **k: ("OK", "rotated_layout", 99))
    # force the legality guard to see a rotation
    monkeypatch.setattr(seed_search, "rotated_buildings", lambda lay, dims: [object()])
    assert seed_search._solve_one(layout, pat, 0, probe_limit=1.0) is None


def test_solve_one_skips_non_sat_and_non_ok(monkeypatch):
    layout, pat = _toy(), Pattern(Footprint(0, 0, 2, 2), frozenset({(0, 2)}), {})
    monkeypatch.setattr(seed_search, "probe", lambda *a, **k: ("UNKNOWN", None))
    assert seed_search._solve_one(layout, pat, 0, probe_limit=1.0) is None
    monkeypatch.setattr(seed_search, "probe", lambda *a, **k: ("SAT", {}))
    monkeypatch.setattr(seed_search, "validate",
                        lambda *a, **k: ("SAT_FILLER_FAIL", None, 0))
    assert seed_search._solve_one(layout, pat, 0, probe_limit=1.0) is None


# --- real end-to-end on a toy (exercises probe + validate for real) --------

def test_end_to_end_on_toy_returns_legal_layout():
    pytest.importorskip("ortools")
    layout = _toy()
    region = set(layout.region.cells)
    pat = next(p for p in generate_patterns(region, 2, 2, 1, random.Random(0), 50)
               if prefilter(p, region, layout.road_needing()) is None)
    res = seed_search.seed_minimize_roads(layout, pat, seeds=range(3),
                                          probe_limit=10.0)
    assert res.achieved is not None and res.achieved >= 1
    assert res.layout is not None
    from foeopt.validate import is_valid, canonical_dims, rotated_buildings
    assert is_valid(res.layout)
    assert rotated_buildings(res.layout, canonical_dims(layout)) == []
