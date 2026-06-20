from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packer import PackConfig, PackResult, classify, bbox, build_candidate, repack
from foeopt.validate import is_valid


def _b(eid, x, y, w, l, needs=False, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic", Footprint(x, y, w, l),
                    needs_road=needs, road_level=1, is_townhall=th,
                    set_id=None, chain_id=None, name=f"b{eid}")


def test_classify_splits_townhall_consumers_fillers():
    th = _b(1, 0, 0, 1, 1, th=True)
    cons = _b(2, 2, 0, 1, 1, needs=True)
    fill = _b(3, 4, 0, 1, 1, needs=False)
    layout = Layout(Region(frozenset()), [th, cons, fill], th)
    t, consumers, fillers = classify(layout)
    assert t is th
    assert consumers == [cons]
    assert fillers == [fill]


def test_bbox_from_region():
    region = Region(frozenset({(0, 0), (3, 0), (0, 2)}))
    assert bbox(region) == (4, 3)


def test_packconfig_and_packresult_construct():
    cfg = PackConfig(anchor="bl", seed=0)
    assert cfg.anchor == "bl"
    res = PackResult(layout=Layout(Region(frozenset()), [], None), unplaced=[])
    assert res.unplaced == []


def _full_region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_build_candidate_grows_tree_in_sparse_city():
    from foeopt.packer import build_candidate, PackConfig
    from foeopt.validate import is_valid
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(12, 12), [th, *cons, *fill], th)
    res = build_candidate(layout, PackConfig("bl", 0))
    assert res.unplaced == []
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= layout.region.cells
        assert not (cells & occ)
        occ |= cells
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(layout.buildings)
    # roads should be modest on a sparse city (near the estimate, not the whole map)
    assert len(res.layout.roads) <= 30


def test_build_candidate_reports_unplaced_when_too_tight():
    from foeopt.packer import build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = _b(2, 0, 0, 2, 2, needs=True)
    layout = Layout(_full_region(2, 2), [th, cons], th)  # townhall fills the region
    res = build_candidate(layout, PackConfig("bl", 0))
    assert any(b.entity_id == 2 for b in res.unplaced)


def test_unplaced_has_no_duplicate_entity_ids():
    # 4x4 region: townhall (2x2) + 4 consumers (2x2 each). The region is too
    # tight to place them all, so at least some end up unplaced. Regardless of
    # whether the failure is spatial or a RouteError, no entity_id must appear
    # twice in PackResult.unplaced.
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    layout = Layout(_full_region(4, 4), [th, *cons], th)
    res = build_candidate(layout, PackConfig("bl", 0))
    ids = [b.entity_id for b in res.unplaced]
    assert len(ids) == len(set(ids)), f"Duplicate entity_ids in unplaced: {ids}"


def test_repack_sparse_city_is_valid_and_conserves_buildings():
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(5)]
    layout = Layout(_full_region(12, 12), [th, *cons, *fill], th)
    res = repack(layout, budget_seconds=0.3, seed=0)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(layout.buildings)


def test_repack_prefers_fewer_unplaced():
    # Tight region: some configs may place fewer; repack keeps the best.
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(3)]
    layout = Layout(_full_region(6, 6), [th, *cons], th)
    res = repack(layout, budget_seconds=0.3, seed=0)
    # whatever the outcome, the returned layout never overlaps / leaves region
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= layout.region.cells
        assert not (cells & occ)
        occ |= cells


def test_build_candidate_conserves_buildings_even_when_partial():
    from foeopt.packer import build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(6)]
    fill = [_b(20 + i, 0, 0, 2, 2, needs=False) for i in range(6)]
    layout = Layout(_full_region(5, 5), [th, *cons, *fill], th)  # too tight: some unplaced
    res = build_candidate(layout, PackConfig("bl", 0))
    placed_ids = {b.entity_id for b in res.layout.buildings}
    unplaced_ids = {b.entity_id for b in res.unplaced}
    assert res.unplaced, "region must be tight enough to leave some unplaced"
    assert len(res.layout.buildings) + len(res.unplaced) == len(layout.buildings)
    assert not (placed_ids & unplaced_ids)   # disjoint: no double-listing


def test_repack_sparse_city_valid_and_conserves_buildings():
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(5)]
    layout = Layout(_full_region(14, 14), [th, *cons, *fill], th)
    res = repack(layout, budget_seconds=0.3, seed=0)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(layout.buildings)


def test_build_candidate_deterministic_given_config():
    from foeopt.packer import build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(12, 12), [th, *cons, *fill], th)
    a = build_candidate(layout, PackConfig("tr", 42))
    b = build_candidate(layout, PackConfig("tr", 42))
    pa = {x.entity_id: (x.footprint.x, x.footprint.y) for x in a.layout.buildings}
    pb = {x.entity_id: (x.footprint.x, x.footprint.y) for x in b.layout.buildings}
    assert pa == pb
    assert a.layout.roads == b.layout.roads
    assert [x.entity_id for x in a.unplaced] == [x.entity_id for x in b.unplaced]


def test_repack_deterministic_given_seed():
    from foeopt.packer import repack
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(5)]
    fill = [_b(20 + i, 0, 0, 2, 2, needs=False) for i in range(5)]
    layout = Layout(_full_region(8, 8), [th, *cons, *fill], th)  # tight: not all fit
    # budget 0.0 pins both runs to exactly one trial, so the comparison is not
    # subject to timing-dependent trial counts (same seed -> identical result).
    a = repack(layout, budget_seconds=0.0, seed=7)
    b = repack(layout, budget_seconds=0.0, seed=7)
    assert a.trials == b.trials == 1
    assert len(a.unplaced) == len(b.unplaced)
    assert len(a.layout.roads) == len(b.layout.roads)


def test_repack_no_worse_than_single_pass():
    from foeopt.packer import repack, build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(6)]
    fill = [_b(20 + i, 0, 0, 2, 2, needs=False) for i in range(6)]
    layout = Layout(_full_region(8, 8), [th, *cons, *fill], th)  # tight
    single = build_candidate(layout, PackConfig("bl", 0))
    multi = repack(layout, budget_seconds=0.5, seed=0)
    assert len(multi.unplaced) <= len(single.unplaced)


def test_repack_early_exit_on_sparse():
    from foeopt.packer import repack
    from foeopt.validate import is_valid
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(3)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(20, 20), [th, *cons, *fill], th)  # very sparse
    res = repack(layout, budget_seconds=10.0, seed=0)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert res.trials == 1   # first trial places all -> early exit (no 10s spent)


def test_gapfill_places_filler_freed_by_routing():
    # 3x2 region, 2x2 townhall, two 1x1 fillers, no consumers.
    # The Townhall-border seed cell (2,0) is reserved during the main filler
    # pass, so only (2,1) is free then -> one filler is unplaced. With no
    # consumers, route() returns no roads, freeing the seed (2,0); the gap-fill
    # pass must place the leftover filler there.
    from foeopt.packer import build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    f1 = _b(2, 0, 0, 1, 1, needs=False)
    f2 = _b(3, 0, 0, 1, 1, needs=False)
    layout = Layout(_full_region(3, 2), [th, f1, f2], th)
    res = build_candidate(layout, PackConfig("bl", 0))
    assert res.unplaced == []
    assert len(res.layout.buildings) == 3
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert not (cells & occ)          # no overlap
        occ |= cells


def test_gapfill_skips_road_needing_buildings():
    # Disconnected region: a 2x2 block (for the townhall) plus an isolated cell
    # at (5,5). The townhall has no in-region border cell, so no road seeds and
    # the road-needing building cannot attach -> it is unplaced. The isolated
    # (5,5) is free post-route, but gap-fill must NOT place a road-needing
    # building there (it would have no road).
    from foeopt.packer import build_candidate, PackConfig
    region = Region(frozenset({(0, 0), (1, 0), (0, 1), (1, 1), (5, 5)}))
    th = _b(1, 0, 0, 2, 2, th=True)
    consumer = _b(2, 0, 0, 1, 1, needs=True)
    layout = Layout(region, [th, consumer], th)
    res = build_candidate(layout, PackConfig("bl", 0))
    assert 2 in {b.entity_id for b in res.unplaced}        # road-needing stays unplaced
    assert 2 not in {b.entity_id for b in res.layout.buildings}
