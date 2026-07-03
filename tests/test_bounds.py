from pathlib import Path

import pytest

from foeopt.bounds import bound_adjacency, report_bounds
from foeopt.loader import load_layout
from foeopt.model import Building, Footprint, Layout, Region
from rl.oracle import optimal_roads


def _b(eid, w, l, *, needs=False, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(0, 0, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_adjacency_bound_is_ceil_n_over_3():
    th = _b(1, 2, 2, th=True)
    cons = [_b(10 + i, 2, 2, needs=True) for i in range(4)]
    layout = Layout(_region(10, 10), [th, *cons], th, {})
    assert bound_adjacency(layout) == 2          # ceil(4/3)


def test_bound_le_true_optimum_on_tiny_instance():
    th = _b(1, 2, 2, th=True)
    c1 = _b(10, 2, 2, needs=True)
    c2 = _b(11, 2, 1, needs=True)
    layout = Layout(_region(6, 6), [th, c1, c2], th, {})
    opt = optimal_roads(layout, budget_s=30.0)
    assert opt is not None
    assert bound_adjacency(layout) <= opt


def test_bounds_below_known_achievable_on_user_city(repo_root):
    lay = load_layout(str(repo_root / "city-user-data.json"),
                      str(repo_root / "city-user-data-foe-helper.json"))
    assert report_bounds(lay)["max"] <= 142      # expert-real road count


def test_bounds_below_known_achievable_on_darkzig(repo_root):
    path = repo_root / "darkzig.json"
    if not path.exists():
        pytest.skip("darkzig.json not present")
    lay = load_layout(str(path))
    assert report_bounds(lay)["max"] <= 158      # polish-achieved road count
