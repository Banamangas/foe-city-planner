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


def test_symmetry_breaking_preserves_status_across_patterns():
    """symmetry_breaking must never turn a SAT pattern into UNSAT (or vice
    versa) -- it only orders interchangeable same-size buildings, it must not
    change feasibility. Uses 3 identical 2x2 consumers so the lex-chain
    constraint actually engages (group size > 1), and checks every surviving
    pattern at k=2, not just one."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    consumers = [
        Building(10 + i, f"c1{i}", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
        for i in range(3)
    ]
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    region_set = set(region.cells)
    rng = random.Random(0)
    checked = 0
    for pat in generate_patterns(region_set, 2, 2, 2, rng, 30):
        if prefilter(pat, region_set, consumers) is not None:
            continue
        st_off, _ = probe(pat, region_set, consumers, probe_limit=10.0,
                          symmetry_breaking=False)
        st_on, _ = probe(pat, region_set, consumers, probe_limit=10.0,
                         symmetry_breaking=True)
        assert st_on == st_off, (
            f"symmetry_breaking changed status for pattern {pat.params}: "
            f"off={st_off} on={st_on}")
        checked += 1
    assert checked >= 3, f"expected several surviving patterns to check, got {checked}"


def test_hints_preserve_status_and_use_nearest_valid_anchor():
    """hints= must never turn a SAT pattern into UNSAT (or vice versa) --
    AddHint only biases search, it isn't a hard constraint. Also verify the
    off-grid/out-of-domain hint case: a hint pointing at a cell that isn't in
    that building's opts must not crash probe() (it should snap to the
    nearest valid anchor via _nearest_opt, not raise)."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    region_set = set(region.cells)
    rng = random.Random(0)
    checked = 0
    for pat in generate_patterns(region_set, 2, 2, 1, rng, 50):
        if prefilter(pat, region_set, [c1]) is not None:
            continue
        st_off, _ = probe(pat, region_set, [c1], probe_limit=10.0)
        # Hint points far outside the region entirely -- probe() must snap it
        # to the nearest opt for c1, not crash or change the outcome.
        st_on, _ = probe(pat, region_set, [c1], probe_limit=10.0,
                         hints={c1.entity_id: (999, 999)})
        assert st_on == st_off, (
            f"hints changed status for pattern {pat.params}: off={st_off} on={st_on}")
        checked += 1
    assert checked >= 3, f"expected several surviving patterns to check, got {checked}"


def test_nearest_opt_picks_closest_by_manhattan_distance():
    from foeopt.roads_first import _nearest_opt
    opts = [(0, 0), (5, 5), (2, 3)]
    assert _nearest_opt(opts, (2, 2)) == (2, 3)
    assert _nearest_opt(opts, (10, 10)) == (5, 5)
    assert _nearest_opt(opts, (0, 1)) == (0, 0)


def test_th_stub_cells_in_pattern_detects_flank_cells():
    from foeopt.roads_first import _th_stub_cells_in_pattern
    th = Footprint(2, 2, 2, 2)  # occupies (2,2)-(3,3)
    # the 4 candidate flank cells are (1,2),(4,2),(1,3),(4,3); only 2 present
    roads = frozenset({(1, 2), (4, 3), (9, 9)})
    cells = _th_stub_cells_in_pattern(th, roads)
    assert set(cells) == {(1, 2), (4, 3)}


def test_th_stub_cells_in_pattern_empty_when_absent():
    from foeopt.roads_first import _th_stub_cells_in_pattern
    th = Footprint(2, 2, 2, 2)
    assert _th_stub_cells_in_pattern(th, frozenset({(9, 9)})) == []


def test_stub_priority_hints_caps_at_three_biggest_per_stub():
    """With more than 3 buildings able to touch a stub cell, only the 3
    largest by area get hinted -- matching the load-3 ceiling a stub cell
    can actually serve, and biasing toward the user's heuristic (biggest
    buildings next to the stub)."""
    from foeopt.roads_first import _stub_priority_hints
    th = Footprint(2, 2, 2, 2)
    stub_cell = (1, 2)
    pat = Pattern(th=th, roads=frozenset({stub_cell}), params={})
    # each placed at (2,2) so its left-edge top-row border cell is (1,2)
    sizes = [(1, 1), (2, 1), (1, 2), (2, 2), (3, 3), (4, 4)]  # areas 1,2,2,4,9,16
    buildings = [Building(i + 1, f"c{i}", "g", Footprint(0, 0, w, l),
                          True, 1, False, None, None, f"b{i}")
                for i, (w, l) in enumerate(sizes)]
    cand = [(b, [(2, 2)]) for b in buildings]
    hints = _stub_priority_hints(pat, cand)
    # indices 3,4,5 are areas 4,9,16 -- the 3 largest
    assert set(hints.keys()) == {3, 4, 5}
    assert all(xy == (2, 2) for xy in hints.values())


def test_stub_priority_hints_empty_when_no_stub_cells():
    from foeopt.roads_first import _stub_priority_hints
    th = Footprint(2, 2, 2, 2)
    pat = Pattern(th=th, roads=frozenset({(9, 9)}), params={})
    big = Building(1, "c1", "g", Footprint(0, 0, 4, 4), True, 1, False, None, None, "big")
    assert _stub_priority_hints(pat, [(big, [(2, 2)])]) == {}


def test_stub_priority_preserves_status_across_patterns():
    """stub_priority must never turn a SAT pattern into UNSAT (or vice
    versa) -- AddHint only biases search, it isn't a hard constraint."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    consumers = [
        Building(10 + i, f"c1{i}", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
        for i in range(3)
    ]
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    region_set = set(region.cells)
    rng = random.Random(0)
    checked = 0
    for pat in generate_patterns(region_set, 2, 2, 2, rng, 30):
        if prefilter(pat, region_set, consumers) is not None:
            continue
        st_off, _ = probe(pat, region_set, consumers, probe_limit=10.0,
                          stub_priority=False)
        st_on, _ = probe(pat, region_set, consumers, probe_limit=10.0,
                         stub_priority=True)
        assert st_on == st_off, (
            f"stub_priority changed status for pattern {pat.params}: "
            f"off={st_off} on={st_on}")
        checked += 1
    assert checked >= 3, f"expected several surviving patterns to check, got {checked}"


def test_solver_overrides_reach_the_real_solver_parameters():
    """solver_overrides must actually apply to solver.parameters, not be a
    silent no-op -- proven by an invalid field name raising (a stub/no-op
    could never raise this way, since it never touches a real protobuf
    message)."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    consumer = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    region_set = set(region.cells)
    pats = list(generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    pat = next(p for p in pats if prefilter(p, region_set, [consumer]) is None)
    with pytest.raises(AttributeError):
        probe(pat, region_set, [consumer], probe_limit=5.0,
             solver_overrides={"this_is_not_a_real_cp_sat_parameter": 1})


def test_solver_overrides_can_shrink_the_effective_time_budget():
    """A solver_overrides entry must be applied *after* (and so can override)
    the probe_limit-derived default -- proven by overriding
    max_time_in_seconds to a near-zero value on a pattern that normally
    resolves within probe_limit, and observing UNKNOWN instead."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    consumers = [
        Building(10 + i, f"c1{i}", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
        for i in range(3)
    ]
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    region_set = set(region.cells)
    pats = list(generate_patterns(region_set, 2, 2, 2, random.Random(0), 30))
    pat = next(p for p in pats if prefilter(p, region_set, consumers) is None)
    st_normal, _ = probe(pat, region_set, consumers, probe_limit=10.0)
    assert st_normal in ("SAT", "UNSAT"), (
        "test setup needs a pattern that normally decides within 10s")
    st_starved, _ = probe(pat, region_set, consumers, probe_limit=10.0,
                          solver_overrides={"max_time_in_seconds": 1e-6})
    assert st_starved == "UNKNOWN", (
        "solver_overrides did not take effect: expected the near-zero override "
        "to starve the solver into UNKNOWN")


def test_solver_overrides_default_none_preserves_status():
    """solver_overrides=None (the default) must behave exactly like omitting
    the kwarg entirely -- no accidental behavior change for every existing
    call site."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    consumers = [
        Building(10 + i, f"c1{i}", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
        for i in range(3)
    ]
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    region_set = set(region.cells)
    pats = list(generate_patterns(region_set, 2, 2, 2, random.Random(0), 30))
    pat = next(p for p in pats if prefilter(p, region_set, consumers) is None)
    st_omitted, _ = probe(pat, region_set, consumers, probe_limit=10.0)
    st_explicit_none, _ = probe(pat, region_set, consumers, probe_limit=10.0,
                                solver_overrides=None)
    assert st_omitted == st_explicit_none


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
