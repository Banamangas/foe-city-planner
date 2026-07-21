"""Correctness gate for next-things-to-try #6 (foeopt/minroads.py): a
joint minimize-roads + placement + connectivity CP-SAT model, compared
against the existing exact brute-force oracle (rl/oracle.py) on toy
instances. This is a correctness bar, not a performance one -- see
tasks/lessons.md 2026-07-17 for the darkzig-scale tractability result."""
from dataclasses import replace

import pytest

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route
from foeopt.validate import is_valid


def _th(w=2, l=2):
    return Building(1, "c1", "main_building", Footprint(0, 0, w, l),
                    False, 1, True, None, None, "TH")


def _consumer(entity_id, w, l):
    return Building(entity_id, f"c{entity_id}", "g", Footprint(0, 0, w, l),
                    True, 1, False, None, None, f"b{entity_id}")


def test_matches_oracle_on_two_building_toy():
    pytest.importorskip("ortools")
    from foeopt.minroads import solve_min_roads
    from rl.oracle import optimal_roads

    th = _th()
    c1 = _consumer(10, 2, 2)
    c2 = _consumer(11, 2, 1)
    region_cells = frozenset((x, y) for x in range(6) for y in range(6))
    lay = Layout(Region(region_cells), [th, c1, c2], th, {})
    oracle = optimal_roads(lay, budget_s=30.0)

    st, roads, positions = solve_min_roads(lay, set(region_cells), time_limit=30.0)
    assert st == "OPTIMAL"
    assert len(roads) == oracle


def test_matches_oracle_on_three_building_toy():
    pytest.importorskip("ortools")
    from foeopt.minroads import solve_min_roads
    from rl.oracle import optimal_roads

    th = _th()
    buildings = [th, _consumer(10, 1, 1), _consumer(11, 1, 1), _consumer(12, 1, 1)]
    region_cells = frozenset((x, y) for x in range(6) for y in range(6))
    lay = Layout(Region(region_cells), buildings, th, {})
    oracle = optimal_roads(lay, budget_s=30.0)

    st, roads, positions = solve_min_roads(lay, set(region_cells), time_limit=30.0)
    assert st == "OPTIMAL"
    assert len(roads) == oracle


def test_matches_oracle_on_four_building_toy():
    pytest.importorskip("ortools")
    from foeopt.minroads import solve_min_roads
    from rl.oracle import optimal_roads

    th = _th()
    buildings = [th, _consumer(20, 2, 1), _consumer(21, 1, 2),
                _consumer(22, 1, 1), _consumer(23, 1, 1)]
    region_cells = frozenset((x, y) for x in range(5) for y in range(5))
    lay = Layout(Region(region_cells), buildings, th, {})
    oracle = optimal_roads(lay, budget_s=30.0)

    st, roads, positions = solve_min_roads(lay, set(region_cells), time_limit=30.0)
    assert st == "OPTIMAL"
    assert len(roads) == oracle


def test_solution_independently_validates_via_real_router():
    """Not just trust the model's own claims -- feed its chosen positions
    through the project's real route()/is_valid() and confirm they produce
    the exact same road cell(s) and a genuinely valid layout."""
    pytest.importorskip("ortools")
    from foeopt.minroads import solve_min_roads

    th = _th()
    c1 = _consumer(10, 2, 2)
    c2 = _consumer(11, 2, 1)
    region_cells = frozenset((x, y) for x in range(6) for y in range(6))
    lay = Layout(Region(region_cells), [th, c1, c2], th, {})

    st, roads, positions = solve_min_roads(lay, set(region_cells), time_limit=30.0)
    assert st == "OPTIMAL"

    placed = [th]
    for b in (c1, c2):
        x, y, w, l = positions[b.entity_id]
        placed.append(replace(b, footprint=Footprint(x, y, w, l)))
    cand = Layout(lay.region, placed, th, {})
    real_roads = route(cand)
    cand.roads = real_roads
    assert set(real_roads.keys()) == set(roads)
    assert is_valid(cand)
