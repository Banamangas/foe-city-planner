import pytest

from foeopt.exact_packing import apply_placements, exact_pack
from foeopt.model import Building, Footprint


def mk(eid, w, l):
    return Building(eid, f"c{eid}", "g", Footprint(0, 0, w, l), False, 1, False,
                    None, None, f"b{eid}")


def box(w, h):
    return {(x, y) for x in range(w) for y in range(h)}


def no_overlap(placements):
    seen = set()
    for b, x, y in placements:
        cells = {(x + dx, y + dy)
                 for dx in range(b.footprint.width)
                 for dy in range(b.footprint.length)}
        assert not (cells & seen), f"{b.entity_id} overlaps"
        seen |= cells
    return seen


def test_perfect_tiling_places_everything():
    # four 2x2 exactly fill a 4x4
    placed, unplaced = exact_pack(box(4, 4), 4, 4, [mk(i, 2, 2) for i in range(4)], 10.0)
    assert unplaced == []
    assert len(placed) == 4
    assert no_overlap(placed) == box(4, 4)


def test_stays_inside_free_space():
    # an L-shaped region: the 4x4 corner is missing
    free = box(8, 8) - box(4, 4)
    placed, _ = exact_pack(free, 8, 8, [mk(i, 2, 2) for i in range(12)], 10.0)
    cells = no_overlap(placed)
    assert cells <= free


def test_reports_what_cannot_fit():
    # five 2x2 into a 4x4 -- one must be left over
    placed, unplaced = exact_pack(box(4, 4), 4, 4, [mk(i, 2, 2) for i in range(5)], 10.0)
    assert len(placed) == 4
    assert len(unplaced) == 1


def test_building_too_large_is_unplaced_not_crashed():
    placed, unplaced = exact_pack(box(3, 3), 3, 3, [mk(0, 5, 5)], 10.0)
    assert placed == []
    assert len(unplaced) == 1


def test_never_rotates():
    """A 4x2 must not be placed as a 2x4 -- rotation is illegal in FoE."""
    free = {(x, y) for x in range(2) for y in range(4)}  # a 2-wide, 4-tall slot
    placed, unplaced = exact_pack(free, 2, 4, [mk(0, 4, 2)], 10.0)
    assert placed == []
    assert len(unplaced) == 1


def test_beats_greedy_where_greedy_wedges_itself():
    """A 4x2 down the middle of a 4x4 leaves two 4x1 strips and blocks the
    remaining 2x2s; the exact model simply avoids that placement."""
    fillers = [mk(0, 4, 2), mk(1, 2, 2), mk(2, 2, 2)]
    placed, unplaced = exact_pack(box(4, 4), 4, 4, fillers, 10.0)
    assert unplaced == []
    assert no_overlap(placed) == box(4, 4)


def test_hint_is_accepted_and_not_worsened():
    fillers = [mk(i, 2, 2) for i in range(4)]
    hint = [(fillers[0], 0, 0), (fillers[1], 2, 0)]
    placed, unplaced = exact_pack(box(4, 4), 4, 4, fillers, 10.0, hint=hint)
    assert len(placed) >= len(hint)
    assert unplaced == []


def test_hint_with_stale_position_is_ignored_not_fatal():
    fillers = [mk(i, 2, 2) for i in range(4)]
    bogus = [(fillers[0], 99, 99)]
    placed, unplaced = exact_pack(box(4, 4), 4, 4, fillers, 10.0, hint=bogus)
    assert unplaced == []


def test_size_classes_share_positions_correctly():
    """Mixed sizes must still tile exactly: 2x2 + two 1x2 fill a 4x2."""
    free = {(x, y) for x in range(4) for y in range(2)}
    fillers = [mk(0, 2, 2), mk(1, 1, 2), mk(2, 1, 2)]
    placed, unplaced = exact_pack(free, 4, 2, fillers, 10.0)
    assert unplaced == []
    assert no_overlap(placed) == free


def test_empty_filler_list():
    placed, unplaced = exact_pack(box(4, 4), 4, 4, [], 10.0)
    assert placed == []
    assert unplaced == []


def test_apply_placements_sets_footprints():
    b = mk(7, 2, 3)
    out = apply_placements([(b, 4, 5)])
    assert out[0].footprint == Footprint(4, 5, 2, 3)
    assert out[0].entity_id == 7
    # original untouched
    assert b.footprint == Footprint(0, 0, 2, 3)


def test_identical_buildings_are_interchangeable():
    """All four 2x2 are distinct objects; each must appear exactly once."""
    fillers = [mk(i, 2, 2) for i in range(4)]
    placed, _ = exact_pack(box(4, 4), 4, 4, fillers, 10.0)
    assert sorted(b.entity_id for b, _, _ in placed) == [0, 1, 2, 3]


@pytest.mark.parametrize("objective", ["count", "area"])
def test_both_objectives_solve_a_feasible_instance(objective):
    placed, unplaced = exact_pack(box(4, 4), 4, 4, [mk(i, 2, 2) for i in range(4)],
                                  10.0, objective=objective)
    assert unplaced == []


# --- instances where the shipped greedy packer provably wedges itself --------
# Found by exhaustive search over perfect guillotine tilings (so feasibility is
# certain by construction), then filtered to those greedy cannot finish.
GREEDY_WEDGES = [
    (4, 4, [(2, 2), (2, 2), (1, 4), (1, 3), (1, 1)]),
    (6, 7, [(2, 6), (3, 1), (3, 1), (4, 1), (4, 5)]),
    (8, 5, [(1, 3), (6, 2), (2, 2), (7, 1), (7, 2)]),
    (8, 7, [(1, 7), (2, 4), (5, 3), (5, 1), (1, 3), (6, 3)]),
    (6, 5, [(4, 2), (1, 5), (1, 5), (2, 3), (2, 3)]),
]


@pytest.mark.parametrize("W,H,sizes", GREEDY_WEDGES)
def test_rescues_layouts_the_greedy_packer_discards(W, H, sizes):
    from types import SimpleNamespace
    from foeopt.packing import Grid
    from foeopt.roads_first import _place_fillers

    fillers = [mk(i, w, l) for i, (w, l) in enumerate(sizes)]
    assert sum(w * l for w, l in sizes) == W * H, "instance must tile exactly"

    grid = Grid(W, H, set())
    cand = SimpleNamespace(buildings=[])
    greedy_unplaced = _place_fillers(grid, fillers, cand)
    assert greedy_unplaced, "fixture is only interesting if greedy fails"

    hint = [(b, b.footprint.x, b.footprint.y) for b in cand.buildings]
    placed, unplaced = exact_pack(box(W, H), W, H, fillers, 10.0, hint=hint)
    assert unplaced == [], "exact packing should finish what greedy could not"
    assert no_overlap(placed) == box(W, H)


# --- wiring into validate() --------------------------------------------------

def _tiny_validate_case():
    """Smallest layout that reaches validate()'s filler stage: 6x6, TH + one
    consumer, solved by probe so route() has something legal to work with."""
    import random
    from foeopt.model import Layout, Region
    from foeopt.roads_first import generate_patterns, prefilter, probe

    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False,
                  None, None, "a")
    filler = mk(20, 2, 2)
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1, filler], th, {})
    cells = set(region.cells)
    for pat in generate_patterns(cells, 2, 2, 1, random.Random(0), 50):
        if prefilter(pat, cells, [c1]) is not None:
            continue
        st, pos = probe(pat, cells, [c1], probe_limit=30.0)
        if st == "SAT":
            return lay, pat, pos
    pytest.skip("no SAT pattern found for the fixture")


def test_validate_default_never_calls_the_exact_packer():
    """exact_repair defaults to 0.0, so existing behaviour is byte-identical
    and no CP-SAT cost is added to the hot path."""
    pytest.importorskip("ortools")
    import foeopt.roads_first as rf

    lay, pat, pos = _tiny_validate_case()
    calls = []
    orig = rf.exact_pack
    rf.exact_pack = lambda *a, **k: calls.append(1) or orig(*a, **k)
    try:
        vstat, _, _ = rf.validate(lay, pat, pos)
    finally:
        rf.exact_pack = orig
    assert vstat == "OK"
    assert calls == []


def test_validate_skips_repair_when_greedy_already_succeeded():
    """The repair is for layouts that would otherwise be discarded; paying for
    it when greedy already finished would be pure waste."""
    pytest.importorskip("ortools")
    import foeopt.roads_first as rf

    lay, pat, pos = _tiny_validate_case()
    calls = []
    orig = rf.exact_pack
    rf.exact_pack = lambda *a, **k: calls.append(1) or orig(*a, **k)
    try:
        vstat, _, _ = rf.validate(lay, pat, pos, exact_repair=10.0)
    finally:
        rf.exact_pack = orig
    assert vstat == "OK"
    assert calls == []


def test_validate_repair_turns_filler_fail_into_ok():
    """Force greedy to fail; the repair must rescue the layout and the rescued
    layout must carry the fillers the solver placed."""
    pytest.importorskip("ortools")
    import foeopt.roads_first as rf

    lay, pat, pos = _tiny_validate_case()
    filler = [b for b in lay.buildings if not b.needs_road and not b.is_townhall][0]

    def sabotage(grid, fillers, cand):
        return list(fillers)          # place nothing, report total failure

    orig_place = rf._place_fillers
    rf._place_fillers = sabotage
    try:
        fail, _, _ = rf.validate(lay, pat, pos)
        ok, vlay, _ = rf.validate(lay, pat, pos, exact_repair=10.0)
    finally:
        rf._place_fillers = orig_place

    assert fail == "SAT_FILLER_FAIL"
    assert ok == "OK"
    assert any(b.entity_id == filler.entity_id for b in vlay.buildings)


def test_validate_repair_keeps_greedy_result_when_it_cannot_improve():
    """If the exact packer also cannot place everything, the layout still fails
    -- the repair must not silently emit a partial layout as OK."""
    pytest.importorskip("ortools")
    import foeopt.roads_first as rf
    from foeopt.model import Layout, Region

    lay, pat, pos = _tiny_validate_case()
    # a filler far too large for anything the consumers left behind
    huge = mk(21, 6, 6)
    lay2 = Layout(lay.region, [*lay.buildings, huge], lay.townhall, {})
    vstat, vlay, _ = rf.validate(lay2, pat, pos, exact_repair=5.0)
    assert vstat == "SAT_FILLER_FAIL"
    assert vlay is None


def test_exact_repair_is_exposed_end_to_end():
    """The knob must reach the solver from the webapp panel and the CLI, or it
    is unreachable in production no matter how well it works."""
    import inspect
    from webapp.params import OPTION_SPECS
    from webapp.runner import JobManager
    from foeopt.roads_first import RoadsFirstSearch

    spec = next(s for s in OPTION_SPECS if s["name"] == "exact_repair")
    assert spec["default"] == 0.0, "must be off by default -- it costs CP-SAT time"
    assert spec["type"] == "float"
    for fn in (JobManager.submit, RoadsFirstSearch.__init__):
        params = inspect.signature(fn).parameters
        assert "exact_repair" in params, fn
        assert params["exact_repair"].default == 0.0


def test_repair_is_clamped_to_one_probe_limit():
    """The repair is paid per rescued layout, so an unclamped budget would let
    N filler failures add N x exact_repair seconds to the time box. A rescue
    must never cost more than the probe that produced it."""
    import foeopt.roads_first as rf

    seen = {}

    def spy(layout, pat, pos, exact_repair=0.0, exact_workers=8,
            exact_objective="count"):
        seen["limit"] = exact_repair
        seen["workers"] = exact_workers
        return ("OK", None, 0)

    orig_validate, orig_probe = rf.validate, rf.probe
    orig_limit, orig_repair = rf._WORKER_PROBE_LIMIT, rf._WORKER_EXACT_REPAIR
    orig_layout = rf._WORKER_LAYOUT

    class _Lay:
        region = type("R", (), {"cells": frozenset({(0, 0)})})()
        def road_needing(self): return []

    rf.validate = spy
    rf.probe = lambda *a, **k: ("SAT", {})
    rf._WORKER_LAYOUT = _Lay()
    rf._WORKER_PROBE_LIMIT = 30.0
    rf._WORKER_EXACT_REPAIR = 300.0        # absurd on purpose
    try:
        rf._run_probe((SimplePattern(), 1, 0))
    finally:
        rf.validate, rf.probe = orig_validate, orig_probe
        rf._WORKER_PROBE_LIMIT, rf._WORKER_EXACT_REPAIR = orig_limit, orig_repair
        rf._WORKER_LAYOUT = orig_layout

    assert seen["limit"] == 30.0, "must clamp to the probe limit, not 300s"


def test_repair_is_never_run_single_threaded():
    """Single-threaded, this model returns no solution at all below 60s -- the
    repair must inherit the probe's thread count, not CP-SAT's default of 1."""
    import inspect
    from foeopt.exact_packing import exact_pack as ep
    from foeopt.roads_first import validate as v

    assert inspect.signature(ep).parameters["workers"].default > 1
    assert inspect.signature(v).parameters["exact_workers"].default > 1


class SimplePattern:
    th = Footprint(0, 0, 1, 1)
    roads = frozenset()
    params: dict = {}
