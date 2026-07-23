import random
from foeopt.roads_first import (
    Pattern, generate_patterns, generate_lane_patterns, prefilter,
    th_anchor_candidates, _check_pattern,
)


def test_pattern_is_frozen_dataclass():
    p = Pattern(th=__import__("foeopt.model", fromlist=["Footprint"]).Footprint(0, 0, 2, 2),
                roads=frozenset({(0, 2)}), params={"k": 1})
    assert p.params == {"k": 1}
    assert isinstance(p.roads, frozenset)


def test_generate_patterns_k0_returns_empty():
    region = set((x, y) for x in range(6) for y in range(6))
    pats = generate_patterns(region, 2, 2, 0, random.Random(0), 50)
    assert pats == []


def test_generate_patterns_k1_yields_patterns():
    region = set((x, y) for x in range(6) for y in range(6))
    pats = generate_patterns(region, 2, 2, 1, random.Random(0), 50)
    assert len(pats) > 0
    for p in pats:
        assert len(p.roads) == 1
        assert p.roads <= region


def test_th_anchor_candidates_full_mode_yields_many():
    region = set((x, y) for x in range(10) for y in range(10))
    cands = th_anchor_candidates(region, 2, 2, mode="full")
    assert len(cands) > 10
    for fp in cands:
        assert fp.cells() <= frozenset(region)


def test_th_anchor_candidates_coarse_mode_yields_few():
    region = set((x, y) for x in range(10) for y in range(10))
    cands = th_anchor_candidates(region, 2, 2, mode="coarse")
    assert len(cands) >= 1
    assert len(cands) < 20


def test_generate_lane_patterns_k0_returns_empty():
    region = set((x, y) for x in range(6) for y in range(6))
    pats = generate_lane_patterns(region, 2, 2, 0, random.Random(0), 50)
    assert pats == []


def test_generate_lane_patterns_connectivity_and_exact_k():
    """Every lane pattern must satisfy _check_pattern's invariant (exact k,
    within region, disjoint from TH, and connected by BFS to a TH-border
    road cell) -- the same rule generate_patterns's output must satisfy,
    across a range of k on a region big enough for the TH to land away
    from a corner (where the trunk anchor sits mid-list, not at index 0).
    k=8 is near the family's natural minimum (a lane needs pitch>=5 cells
    of trunk just to reach one seed, unlike the comb family which can
    produce k=1 patterns) -- below that the family legitimately has no
    patterns, which is expected and not tested here."""
    region = set((x, y) for x in range(16) for y in range(16))
    for k in (8, 20, 40):
        pats = generate_lane_patterns(region, 2, 2, k, random.Random(0), 50, th_mode="full")
        assert pats, f"expected patterns at k={k}"
        for p in pats:
            _check_pattern(p, region, k)


def test_generate_lane_patterns_th_off_corner_anchor_mid_trunk():
    """Regression guard for the mid-trunk anchor bug: when the TH sits away
    from a region corner, _trunk()'s returned list has the TH-adjacent
    anchor cell in the middle, not at index 0. A naive trunk[:n] prefix
    (as generate_patterns's comb family uses) would miss the anchor and
    produce a disconnected pattern. Force a mid-region TH via th_mode=full
    on a large region and confirm every survivor is still connected."""
    region = set((x, y) for x in range(20) for y in range(20))
    pats = generate_lane_patterns(region, 2, 2, 30, random.Random(1), 80, th_mode="full")
    assert pats
    mid_region_used = any(5 < p.th.x < 15 and 5 < p.th.y < 15 for p in pats)
    assert mid_region_used, "expected at least one non-corner TH placement in this sample"
    for p in pats:
        _check_pattern(p, region, 30)


def test_generate_lane_patterns_max_lane_len_none_matches_unbounded_default():
    """max_lane_len=None (the default) must produce byte-identical output to
    calling without the kwarg at all -- capping is strictly opt-in and must
    not perturb the already-measured uncapped lane-family results."""
    region = set((x, y) for x in range(16) for y in range(16))
    for k in (20, 40):
        a = generate_lane_patterns(region, 2, 2, k, random.Random(0), 50, th_mode="full")
        b = generate_lane_patterns(region, 2, 2, k, random.Random(0), 50, th_mode="full",
                                   max_lane_len=None)
        assert a == b


def test_generate_lane_patterns_capped_connectivity_and_exact_k():
    """Capped lanes must still satisfy _check_pattern (connectivity, exact
    k, region/TH-disjointness) across a few k values and cap sizes."""
    region = set((x, y) for x in range(20) for y in range(20))
    for cap in (2, 4, 6):
        for k in (15, 25, 40):
            pats = generate_lane_patterns(region, 2, 2, k, random.Random(0), 50,
                                          th_mode="full", max_lane_len=cap)
            for p in pats:
                _check_pattern(p, region, k)


def test_generate_lane_patterns_max_lane_len_bounds_each_front():
    """The cap must actually bound how far a lane grows -- re-derive each
    pattern's trunk/seeds the same way the generator does and confirm no
    front extends past the cap in the output road set."""
    from foeopt.roads_first import _trunk, _th_anchor_cell
    region = set((x, y) for x in range(20) for y in range(20))
    cap = 2
    checked = 0
    for k in (10, 15, 20, 25):
        pats = generate_lane_patterns(region, 2, 2, k, random.Random(2), 40,
                                      th_mode="full", max_lane_len=cap)
        for pat in pats:
            th = pat.th
            side = pat.params["side"]
            th_cells = th.cells()
            trunk_raw = [c for c in _trunk(region, th, side) if c not in th_cells]
            anchor = _th_anchor_cell(th, side)
            anchor_idx = trunk_raw.index(anchor)
            pitch = pat.params["pitch"]
            pos_idxs = list(range(anchor_idx + pitch, len(trunk_raw), pitch))
            neg_idxs = list(range(anchor_idx - pitch, -1, -pitch))
            seed_idxs = sorted(pos_idxs + neg_idxs)
            seeds = [trunk_raw[i] for i in seed_idxs]
            horiz = trunk_raw[0][1] == trunk_raw[-1][1]
            cand_dirs = [(0, -1), (0, 1)] if horiz else [(-1, 0), (1, 0)]
            for s in seeds:
                for d in cand_dirs:
                    dist = 1
                    while (s[0] + d[0] * dist, s[1] + d[1] * dist) in pat.roads:
                        dist += 1
                    assert dist - 1 <= cap, (
                        f"lane front from seed {s} dir {d} extended "
                        f"{dist - 1} cells > cap {cap}")
                    checked += 1
    assert checked > 0, "expected at least one capped pattern to check"


def test_prefilter_adjacency_capacity_counts_actual_free_neighbors():
    """A road cell with only 1 truly-free orthogonal neighbor (the rest
    blocked by TH/out-of-region) must contribute capacity 1, not a flat 3 --
    the tightened bound must catch a case the old flat-3 check would have
    missed. Region: TH at (0,0)-(1,1), road cell at (2,0) whose only free
    neighbor is (2,1) ((1,0) is TH, (3,0)/(2,-1) are out of region)."""
    from foeopt.model import Building, Footprint
    th_fp = Footprint(0, 0, 2, 2)
    # (5,5) is an unrelated free cell added only so the area check has
    # enough slack to pass and the adjacency-capacity check is the one
    # actually exercised here.
    region = {(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1), (5, 5)}
    pat = Pattern(th=th_fp, roads=frozenset({(2, 0)}), params={"k": 1})
    # 2 tiny consumers -- old flat-3 check would accept (capacity 3 >= 2);
    # the true free-neighbor count here is 1, so the tightened check must reject.
    c1 = Building(1, "c1", "g", Footprint(0, 0, 1, 1), True, 1, False, None, None, "a")
    c2 = Building(2, "c2", "g", Footprint(0, 0, 1, 1), True, 1, False, None, None, "b")
    reason = prefilter(pat, region, [c1, c2])
    assert reason == "adjacency-capacity"


def test_prefilter_adjacency_capacity_still_accepts_when_truly_sufficient():
    """Same road-cell geometry, but only 1 consumer -- capacity 1 >= 1
    demand, must not be rejected."""
    from foeopt.model import Building, Footprint
    th_fp = Footprint(0, 0, 2, 2)
    region = {(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1)}
    pat = Pattern(th=th_fp, roads=frozenset({(2, 0)}), params={"k": 1})
    c1 = Building(1, "c1", "g", Footprint(0, 0, 1, 1), True, 1, False, None, None, "a")
    reason = prefilter(pat, region, [c1])
    assert reason is None


def test_prefilter_area_rejects_impossible():
    from foeopt.model import Building, Footprint
    th_fp = Footprint(0, 0, 2, 2)
    pat = Pattern(th=th_fp, roads=frozenset({(2, 0), (2, 1)}), params={"k": 2})
    region = set((x, y) for x in range(4) for y in range(4))
    big = Building(1, "c", "g", Footprint(0, 0, 4, 4), True, 1, False, None, None, "big")
    reason = prefilter(pat, region, [big])
    assert reason == "area"

def test_max_lane_len_only_filters_never_creates_new_topologies():
    """`max_lane_len` cannot make a skeleton the uncapped generator wouldn't
    already produce: fronts grow round-robin, so a cap either sits above the
    natural lane length (inert) or starves growth until `remaining != 0`
    rejects the pattern outright. The capped set is therefore always a strict
    SUBSET of the uncapped one -- so treating a capped run as a separate
    "hybrid family" probes a subsample of `lane`, not a different structure.
    """
    import random
    from foeopt.roads_first import generate_lane_patterns
    region = {(x, y) for x in range(20) for y in range(20)}
    uncapped = {p.roads for p in generate_lane_patterns(
        region, 2, 2, 20, random.Random(0), 10**9, th_mode="full")}
    capped = {p.roads for p in generate_lane_patterns(
        region, 2, 2, 20, random.Random(0), 10**9, th_mode="full", max_lane_len=3)}
    assert capped, "test needs a cap that still yields patterns"
    assert not (capped - uncapped), "cap produced a topology lane cannot produce"
    assert len(capped) < len(uncapped), "test needs a cap that actually binds"
