import random
import pytest
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import probe, validate, generate_patterns, prefilter, Pattern


def test_probe_returns_unsat_when_no_anchors():
    """A consumer too big for the region after roads+TH occupy space -> UNSAT."""
    th = Building(1, "c1", "main_building", Footprint(0, 0, 1, 1),
                  False, 1, True, None, None, "TH")
    consumer = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(2) for y in range(2)))
    lay = Layout(region, [th, consumer], th, {})
    pats = list(generate_patterns(set(region.cells), 1, 1, 1, random.Random(0), 5))
    assert pats
    pat = pats[0]
    st, pos = probe(pat, set(region.cells), [consumer], probe_limit=5.0)
    assert st == "UNSAT"
    assert pos is None


def test_validate_returns_ok_on_simple_satisfiable():
    """End-to-end: a 6x6 region with TH + 1 consumer at k=1 should validate OK
    when probe finds a SAT placement. Requires ortools."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})
    region_set = set(region.cells)
    rng = random.Random(0)
    found_ok = False
    for pat in generate_patterns(region_set, 2, 2, 1, rng, 50):
        if prefilter(pat, region_set, [c1]) is not None:
            continue
        st, pos = probe(pat, region_set, [c1], probe_limit=30.0)
        if st != "SAT":
            continue
        vstat, vlay, achieved = validate(lay, pat, pos)
        if vstat == "OK":
            found_ok = True
            assert achieved == 1
            assert len(vlay.buildings) >= 2
            break
    assert found_ok, "expected at least one OK validation"
