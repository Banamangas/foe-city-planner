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
    helper = repo_root / "city-user-data-foe-helper.json"
    if not helper.exists():
        pytest.skip("city-user-data-foe-helper.json not present")
    lay = load_layout(str(repo_root / "city-user-data.json"), str(helper))
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
    helper = repo_root / "city-user-data-foe-helper.json"
    if not helper.exists():
        pytest.skip("city-user-data-foe-helper.json not present")
    lay = load_layout(str(repo_root / "city-user-data.json"), str(helper))
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


def test_pick_k_start_margin_is_family_aware():
    """comb/lane are feasible ABOVE sigma_half, nonuniform BELOW it, so the
    margin's sign differs. Changing comb/lane would be an unmeasured behaviour
    change, so they must stay exactly where they were."""
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    # enough consumers that sigma_half is well clear of the max(1, ...) floor,
    # otherwise the negative margin clamps and the comparison tests nothing
    blds = [th] + [
        Building(10 + i, f"c{i}", "g", Footprint(0, 0, 2, 4), True, 1, False,
                 None, None, f"b{i}")
        for i in range(20)
    ]
    region = Region(frozenset((x, y) for x in range(30) for y in range(30)))
    lay = Layout(region, blds, th, {})
    base = pick_k_start(lay)                       # default == comb
    assert base > 20, "fixture too small to exercise the margin"
    assert pick_k_start(lay, "comb") == base
    assert pick_k_start(lay, "lane") == base
    # comb +8, nonuniform +0 -> the families differ by exactly 8.
    # nonuniform was -4 (a gap of 12) until 2026-08-01; see the test below.
    assert pick_k_start(lay, "nonuniform") == base - 8    # +8 -> +0


def test_pick_k_start_nonuniform_matches_the_validated_settings(repo_root):
    """SUPERSEDED 2026-08-01: the margin is now +0, so these are sigma/2 exactly.

    The old -4 (darkzig 111, FR16 84) was calibrated on those two cities and was
    better on both -- FR16 reproduced its record of 76 from 84. It was then
    measured on a third city at equal 600 s boxes and turned out not to be
    survivable: FR17 starting at 117 spends its entire box ascending and returns
    FAMILY_TOO_WEAK, while starting at 121 reaches 115 (beating that city's
    previous best of 123).

    So the change trades a measured ONE road on FR16 (76 -> 77) for FR17 working
    at all. Recorded here rather than silently re-tuned, because the earlier
    numbers were not wrong -- they were calibrated on too few cities.
    """
    import pathlib
    from foeopt.loader import load_layout
    cases = [("darkzig.json", 115), ("CityMap-Born-FR16-2026-07-07.json", 88)]
    checked = 0
    for fname, expected in cases:
        p = pathlib.Path(repo_root) / fname
        if not p.exists():
            continue
        assert pick_k_start(load_layout(str(p)), "nonuniform") == expected
        checked += 1
    if checked == 0:
        pytest.skip("no city fixtures present")


def test_pick_k_start_unknown_family_falls_back_to_the_safe_margin():
    """An unrecognised family must not silently get the aggressive margin --
    too low returns FAMILY_TOO_WEAK (nothing at all), too high only wastes time."""
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    blds = [th, Building(10, "c10", "g", Footprint(0, 0, 2, 4), True, 1, False,
                         None, None, "b")]
    region = Region(frozenset((x, y) for x in range(20) for y in range(20)))
    lay = Layout(region, blds, th, {})
    assert pick_k_start(lay, "does-not-exist") == pick_k_start(lay, "comb")


def test_pick_k_start_stays_positive_for_tiny_cities():
    """A negative margin must never drive k_start to zero or below."""
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    blds = [th, Building(10, "c10", "g", Footprint(0, 0, 1, 1), True, 1, False,
                         None, None, "b")]
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, blds, th, {})
    assert pick_k_start(lay, "nonuniform") >= 1
