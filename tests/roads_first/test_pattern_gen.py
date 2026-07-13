import random
from foeopt.roads_first import Pattern, generate_patterns, prefilter, th_anchor_candidates


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


def test_prefilter_area_rejects_impossible():
    from foeopt.model import Building, Footprint
    th_fp = Footprint(0, 0, 2, 2)
    pat = Pattern(th=th_fp, roads=frozenset({(2, 0), (2, 1)}), params={"k": 2})
    region = set((x, y) for x in range(4) for y in range(4))
    big = Building(1, "c", "g", Footprint(0, 0, 4, 4), True, 1, False, None, None, "big")
    reason = prefilter(pat, region, [big])
    assert reason == "area"