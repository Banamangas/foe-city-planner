"""road_pressure / screen_city are a measured heuristic, not a bound.

These tests lock the arithmetic and the ordering that motivated them -- the
three real cities must land in the right buckets -- without asserting the
thresholds are laws (they are n=3 and confounded; see the docstrings).
"""
from __future__ import annotations

import pytest

from foeopt.bounds import road_pressure, screen_city
from foeopt.model import Building, Footprint, Layout, Region


def _city(side, consumers, filler_area=0):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    blds = [th]
    eid = 10
    for w, l in consumers:
        blds.append(Building(eid, f"c{eid}", "g", Footprint(0, 0, w, l),
                             True, 1, False, None, None, f"b{eid}"))
        eid += 1
    if filler_area:
        blds.append(Building(eid, f"c{eid}", "g", Footprint(0, 0, filler_area, 1),
                             False, 1, False, None, None, "filler"))
    region = Region(frozenset((x, y) for x in range(side) for y in range(side)))
    return Layout(region, blds, th, {})


def test_pressure_is_sigma_half_over_slack():
    # 10x10 region = 100 cells; TH 2x2 = 4; two 2x4 consumers = 16 -> area 20
    # slack = 80; sigma_half = (2 + 2) / 2 = 2  -> pressure = 2/80 = 0.025
    lay = _city(10, [(2, 4), (2, 4)])
    assert road_pressure(lay) == pytest.approx(2.0 / 80.0)


def test_pressure_infinite_when_no_slack():
    """Buildings exceeding the region is infeasible by area accounting -- that
    part IS provable, and must not be reported as a finite ratio."""
    lay = _city(4, [(4, 4), (4, 4)])
    assert road_pressure(lay) == float("inf")
    assert screen_city(lay)["verdict"] == "INFEASIBLE"


def test_screen_buckets_a_roomy_city_as_likely():
    lay = _city(30, [(2, 3)] * 20)
    s = screen_city(lay)
    assert s["verdict"] == "LIKELY"
    assert s["road_pressure"] < 0.5


def test_screen_buckets_a_tight_city_as_unlikely():
    # squeeze slack so sigma_half is a large share of it
    lay = _city(12, [(3, 3)] * 14)
    s = screen_city(lay)
    assert s["road_pressure"] >= 0.8
    assert s["verdict"] in ("UNLIKELY", "INFEASIBLE")


def test_screen_reports_reason_and_inputs():
    lay = _city(20, [(2, 2)] * 10)
    s = screen_city(lay)
    for key in ("road_pressure", "consumers", "slack", "region_cells",
                "building_area", "verdict", "reason"):
        assert key in s
    assert s["reason"]


def test_real_cities_land_in_the_measured_buckets():
    """The ordering this heuristic exists to capture: darkzig and FR16 succeeded
    (pressure 0.40/0.43), FR24 returned 0 SAT in 135 probes (0.89). Skipped when
    the city files are absent."""
    import pathlib
    from foeopt.loader import load_layout
    cases = [("darkzig.json", "LIKELY", 0.5),
             ("CityMap-Born-FR16-2026-07-07.json", "LIKELY", 0.5),
             ("CityMap-Born-FR24-2026-07-07.json", "UNLIKELY", None)]
    checked = 0
    for fname, want, ceiling in cases:
        p = pathlib.Path(fname)
        if not p.exists():
            continue
        s = screen_city(load_layout(str(p)))
        assert s["verdict"] == want, f"{fname}: {s}"
        if ceiling is not None:
            assert s["road_pressure"] < ceiling
        else:
            assert s["road_pressure"] >= 0.8
        checked += 1
    if checked == 0:
        pytest.skip("no city fixtures present")
