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


import math

from foeopt.bounds import pick_k_start


def test_pick_k_start_synthetic_layout():
    """10x10 region (100 cells), TH 2x2 (4 cells), 4 consumers 2x2 each (16 cells).
    building_area = 4 + 16 = 20. k_max = 100 - 20 = 80.
    sigma_half = sum(min(2,2) for 4 consumers) / 2 = 8/2 = 4.
    k_start = min(80, ceil(4) + 8) = min(80, 12) = 12."""
    th = _b(1, 2, 2, th=True)
    cons = [_b(10 + i, 2, 2, needs=True) for i in range(4)]
    layout = Layout(_region(10, 10), [th, *cons], th, {})
    assert pick_k_start(layout) == 12


def test_pick_k_start_clamps_to_k_max():
    """Tight region where sigma_half + 8 exceeds the area ceiling.
    5x5 region (25 cells), TH 2x2 (4), 4 consumers 2x2 (16). building_area = 20.
    k_max = 25 - 20 = 5. sigma_half = 4. sigma_half + 8 = 12.
    k_start = min(5, 12) = 5 (clamped to the area ceiling)."""
    th = _b(1, 2, 2, th=True)
    cons = [_b(10 + i, 2, 2, needs=True) for i in range(4)]
    layout = Layout(_region(5, 5), [th, *cons], th, {})
    assert pick_k_start(layout) == 5


def test_pick_k_start_on_darkzig(repo_root):
    """darkzig: region=2720, building_area=2437, k_max=283, sigma_half=114.5.
    k_start = min(283, ceil(114.5)+8) = min(283, 123) = 123."""
    path = repo_root / "darkzig.json"
    if not path.exists():
        pytest.skip("darkzig.json not present")
    lay = load_layout(str(path))
    assert pick_k_start(lay) == 123


def test_pick_k_start_on_user_city(repo_root):
    """user city: region=4224, building_area=4079, k_max=145, sigma_half=157.0.
    k_start = min(145, ceil(157)+8) = min(145, 165) = 145 (clamped to k_max)."""
    lay = load_layout(str(repo_root / "city-user-data.json"),
                      str(repo_root / "city-user-data-foe-helper.json"))
    assert pick_k_start(lay) == 145


@pytest.mark.parametrize("name,expected", [
    ("CityMap-Born-FR16-2026-07-07.json", 96),    # k_max=206, sigma/2=88 -> min(206, 96) = 96
    ("CityMap-Born-FR17-2026-07-07.json", 129),   # k_max=193, sigma/2=121 -> min(193, 129) = 129
    ("CityMap-Born-FR24-2026-07-07.json", 246),   # k_max=268, sigma/2=238 -> min(268, 246) = 246
])
def test_pick_k_start_on_fr_cities(repo_root, name, expected):
    """Three CityMap-Born-FRxx cities (added 2026-07-07): k_start = min(k_max, ceil(sigma/2)+8)."""
    path = repo_root / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    lay = load_layout(str(path))
    assert pick_k_start(lay) == expected


def test_pick_k_start_never_exceeds_k_max(repo_root):
    """Airtight invariant: k_start <= k_max for any city (the area ceiling)."""
    import glob
    for path in sorted(glob.glob(str(repo_root / "CityMap-Born-FR*.json"))):
        lay = load_layout(path)
        k_max = len(lay.region.cells) - sum(b.footprint.width * b.footprint.length
                                            for b in lay.buildings)
        assert pick_k_start(lay) <= k_max
    # also darkzig and user city
    dz = repo_root / "darkzig.json"
    if dz.exists():
        lay = load_layout(str(dz))
        k_max = len(lay.region.cells) - sum(b.footprint.width * b.footprint.length
                                            for b in lay.buildings)
        assert pick_k_start(lay) <= k_max
