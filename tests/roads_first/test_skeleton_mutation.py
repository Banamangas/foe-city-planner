"""N5: concrete-skeleton mutation operators (foeopt/skeleton_mutation.py)."""
import random

import pytest

from foeopt import skeleton_mutation as sm
from foeopt.model import Footprint
from foeopt.roads_first import Pattern, _check_pattern

TH = Footprint(10, 0, 4, 3)                     # TH at x 10..13, y 0..2
REGION = frozenset((x, y) for x in range(30) for y in range(24))


def comb():
    """Trunk down from the TH's south side at x=11, y 3..15, with branches
    to the east at y = 5, 9, 13 (length 6) and one to the west at y = 9."""
    r = {(11, y) for y in range(3, 16)}
    for y in (5, 9, 13):
        r |= {(x, y) for x in range(12, 18)}
    r |= {(x, 9) for x in range(5, 11)}
    return frozenset(r)


def check(roads):
    _check_pattern(Pattern(TH, roads, {}), set(REGION), len(roads))


def test_comb_fixture_is_a_valid_pattern():
    check(comb())
    assert sm.valid(comb(), TH, REGION)


def test_leaves_and_arm():
    r = comb()
    assert (17, 5) in sm.leaves(r, TH) and (5, 9) in sm.leaves(r, TH)
    assert (11, 15) in sm.leaves(r, TH)
    a = sm.arm(r, TH, (17, 5))
    assert a == [(x, 5) for x in range(17, 11, -1)]   # stops before junction (11,5)
    assert sm._straight_dir(a) == (1, 0)


@pytest.mark.parametrize("name", sorted(sm.OPS))
def test_every_operator_returns_valid_patterns_or_none(name):
    rng = random.Random(0)
    hits = 0
    for _ in range(60):
        out = sm.OPS[name](comb(), TH, REGION, rng)
        if out is None:
            continue
        hits += 1
        assert out != comb()
        check(out)
    assert hits > 0, f"{name} never applied on the comb"


def test_extend_grows_a_leaf_straight():
    r = comb()
    out = sm.extend(r, TH, REGION, random.Random(1))
    added = out - r
    assert added and not (r - out)
    xs, ys = {c[0] for c in added}, {c[1] for c in added}
    assert len(xs) == 1 or len(ys) == 1


def test_shorten_and_remove_only_cut_one_arm():
    r = comb()
    for op in (sm.shorten, sm.remove):
        out = op(r, TH, REGION, random.Random(2))
        cut = r - out
        assert cut and not (out - r)
        assert (11, 3) in out                       # the TH contact survives


def test_shift_moves_an_arm_along_its_trunk():
    r = comb()
    rng = random.Random(3)
    for _ in range(20):
        out = sm.shift(r, TH, REGION, rng)
        assert out is not None
        assert len(out) == len(r)                   # a translation
        check(out)


def test_spoke_uses_a_free_th_side():
    r = comb()
    assert set(sm.free_sides(r, TH)) == {"N", "W", "E"}
    out = sm.spoke(r, TH, REGION, random.Random(4))
    new = out - r
    assert len(new) >= 3
    assert any(c in TH.border_cells() for c in new)
    assert len(sm.free_sides(out, TH)) == 2


def test_merge_replaces_two_parallel_arms_by_one():
    r = comb()
    out = sm.merge(r, TH, REGION, random.Random(5))
    assert out is not None
    check(out)
    # one fewer east branch: exactly two arms left on that side
    east_leaves = [c for c in sm.leaves(out, TH) if c[0] > 11]
    assert len(east_leaves) == 2


def test_growth_never_touches_other_roads():
    r = comb()
    rng = random.Random(6)
    for _ in range(100):
        out = sm.add(r, TH, REGION, rng)
        if out is None:
            continue
        for c in out - r:
            assert len(sm.road_nbrs(c, out)) <= 2


def test_prune_keeps_the_used_network():
    r = comb()
    used = r - {(x, 13) for x in range(12, 18)}
    assert sm.prune(r, TH, REGION, used) == used
    assert sm.prune(r, TH, REGION, None) is None
    assert sm.prune(r, TH, REGION, r) is None       # no change
    assert sm.prune(r, TH, REGION, {(20, 20)}) is None   # disconnected


def test_operators_respect_region_and_th():
    small = frozenset((x, y) for x in range(9, 16) for y in range(0, 12))
    r = frozenset({(11, y) for y in range(3, 10)})
    rng = random.Random(7)
    for _ in range(200):
        res = sm.mutate(r, TH, small, rng, n_ops=2)
        if res is None:
            continue
        out, names = res
        assert out <= small and not (out & TH.cells())
        assert sm.connected_to_th(out, TH)


def test_mutate_is_deterministic_per_seed():
    a = sm.mutate(comb(), TH, REGION, random.Random(9), n_ops=2)
    b = sm.mutate(comb(), TH, REGION, random.Random(9), n_ops=2)
    assert a == b and a is not None


def test_mutants_of_a_real_record_network_are_valid_patterns():
    """darkzig's 88-road record network (with its 2x2 two-lane tile): 300
    random 1-2 move mutants all pass _check_pattern, and the operators fire."""
    import json
    from tests.conftest import REPO_ROOT, require_data
    from foeopt.loader import load_layout
    from scripts.verify_layout_file import load_saved
    src = load_layout(str(require_data("darkzig.json")))
    rec = json.loads((REPO_ROOT / "docs/records/darkzig-88-roads-rebased.json").read_text())
    lay = load_saved(src, rec)
    th, roads = lay.townhall.footprint, frozenset(lay.roads)
    region = frozenset(src.region.cells)
    assert sm.valid(roads, th, region)
    rng = random.Random(11)
    fired = set()
    for _ in range(300):
        res = sm.mutate(roads, th, region, rng, n_ops=1 if rng.random() < 0.7 else 2)
        assert res is not None
        out, names = res
        fired.update(names)
        _check_pattern(Pattern(th, out, {}), set(region), len(out))
    assert sm.prune(roads, th, region, roads - {sm.leaves(roads, th)[0]}) is not None
    assert fired >= {"extend", "shorten", "remove", "add", "shift"}
