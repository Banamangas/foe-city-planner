"""Filler packing: best-fit, and never give up early.

`validate()` places the non-road-needing buildings after CP-SAT has placed the
consumers. The old packer used first-fit and returned at the first building that
did not fit. Measured on 12 real FR16 failures (tasks/lessons.md 2026-07-31):
it placed 11 of 32 where continuing places 31, and recovered 0 of 12 layouts
where best-fit recovers 6.
"""
from __future__ import annotations

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packing import Grid
from foeopt.roads_first import _place_fillers


def _f(eid, w, l):
    return Building(eid, f"c{eid}", "g", Footprint(0, 0, w, l), False, 1, False,
                    None, None, f"b{eid}")


def _blank(side, blocked=()):
    return Grid(side, side, set(blocked))


def _cand():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    region = Region(frozenset((x, y) for x in range(10) for y in range(10)))
    return Layout(region, [th], th, {})


def test_places_everything_when_there_is_room():
    cand = _cand()
    grid = _blank(10)
    unplaced = _place_fillers(grid, [_f(10, 2, 2), _f(11, 3, 1)], cand)
    assert unplaced == []
    assert len(cand.buildings) == 3          # th + 2 fillers


def test_does_not_stop_at_the_first_building_that_does_not_fit():
    """The old behaviour discarded every later placement. A 9x9 building cannot
    fit in a 5x5 grid, but the three 1x1s after it must still be placed."""
    cand = _cand()
    grid = _blank(5)
    fillers = [_f(10, 9, 9), _f(11, 1, 1), _f(12, 1, 1), _f(13, 1, 1)]
    unplaced = _place_fillers(grid, fillers, cand)
    assert [b.entity_id for b in unplaced] == [10]
    assert len(cand.buildings) == 4, "the three that fit must all be placed"


def test_reports_every_building_that_did_not_fit():
    cand = _cand()
    grid = _blank(4)
    fillers = [_f(10, 9, 9), _f(11, 8, 8)]
    unplaced = _place_fillers(grid, fillers, cand)
    assert {b.entity_id for b in unplaced} == {10, 11}
    assert len(cand.buildings) == 1          # th only


def test_prefers_the_tightest_spot_not_the_first():
    """best-fit is the whole point: a first-fit packer takes the top-left corner
    of the open area and can cut it in two. Here the only 1-wide slot is at the
    right edge; a 1x1 must go there rather than into open space."""
    # 6x6 grid, a full-height wall at x=4 leaving a 1-wide channel at x=5
    blocked = {(4, y) for y in range(6)}
    cand = _cand()
    grid = Grid(6, 6, set(blocked))
    _place_fillers(grid, [_f(10, 1, 1)], cand)
    placed = [b for b in cand.buildings if b.entity_id == 10][0]
    assert placed.footprint.x == 5, (
        f"best-fit should use the enclosed channel, got x={placed.footprint.x}")


def test_largest_first_ordering_is_preserved():
    """Big buildings need contiguous space and must get first pick."""
    cand = _cand()
    grid = _blank(6)
    _place_fillers(grid, [_f(10, 1, 1), _f(11, 4, 4)], cand)
    ids = [b.entity_id for b in cand.buildings if b.entity_id in (10, 11)]
    assert ids[0] == 11, "the 4x4 must be placed before the 1x1"


def test_empty_filler_list_is_a_no_op():
    cand = _cand()
    assert _place_fillers(_blank(6), [], cand) == []
    assert len(cand.buildings) == 1


def test_prefilter_counts_fillers_when_given_them():
    """Without fillers the area check can pass a pattern with room for the
    consumers and none for everything else -- a wasted CP-SAT probe that
    surfaces later as SAT_FILLER_FAIL."""
    from foeopt.roads_first import Pattern, prefilter
    region = {(x, y) for x in range(6) for y in range(6)}      # 36 cells
    th = Footprint(0, 0, 2, 2)                                  # 4
    roads = frozenset({(2, 0), (2, 1), (2, 2)})                 # 3
    consumers = [Building(10, "c", "g", Footprint(0, 0, 5, 5), True, 1, False,
                          None, None, "big")]                   # 25
    pat = Pattern(th=th, roads=roads, params={"k": 3})
    # 25 + 3 <= 36 - 4 = 32 -> passes without fillers
    assert prefilter(pat, region, consumers) is None
    # add fillers that cannot possibly fit alongside -> must be rejected
    fillers = [Building(20, "f", "g", Footprint(0, 0, 4, 4), False, 1, False,
                        None, None, "f")]                       # +16 = 41 > 32
    assert prefilter(pat, region, consumers, fillers) == "area"


def test_prefilter_is_unchanged_when_fillers_are_omitted():
    """Backwards compatible: existing callers must behave exactly as before."""
    from foeopt.roads_first import Pattern, prefilter
    region = {(x, y) for x in range(8) for y in range(8)}
    th = Footprint(0, 0, 2, 2)
    pat = Pattern(th=th, roads=frozenset({(2, 0)}), params={"k": 1})
    consumers = [Building(10, "c", "g", Footprint(0, 0, 2, 2), True, 1, False,
                          None, None, "c")]
    assert prefilter(pat, region, consumers) == prefilter(pat, region, consumers, None)
    assert prefilter(pat, region, consumers, []) is None
