"""Q2 step 1: connectivity closures of minimize_needed, and soft skeleton cells."""
import random
from dataclasses import replace

import pytest

from foeopt.legality import check
from foeopt.model import Building, Footprint, Layout, Region, contact_cells
from foeopt.roads_first import (CLOSURES, Pattern, minimize_needed, skeleton_layers,
                                skeleton_parents, validate)
from foeopt.validate import connected_road_cells

pytest.importorskip("ortools")


def _b(eid, w, l, needs=True, th=False, x=0, y=0, level=1):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, level, th, None, None, f"b{eid}")


def _solve(pat, region, consumers, hint, closure, soft=False, limit=10.0):
    diag: dict = {}
    pos = minimize_needed(pat, region, consumers, hint, limit=limit, workers=4,
                          model="position", diag=diag, closure=closure, soft=soft)
    return pos, diag


def _witness_ok(pat, region, consumers, pos, witness):
    """The selected cells form a road network connected to the TH that serves
    every consumer, and no building sits on one of them."""
    th = _b(1, pat.th.width, pat.th.length, needs=False, th=True, x=pat.th.x, y=pat.th.y)
    placed = [replace(b, footprint=Footprint(*pos[b.entity_id])) for b in consumers]
    lay = Layout(Region(frozenset(region)), [th, *placed], th, {c: 1 for c in witness})
    if connected_road_cells(lay) != set(witness):
        return False
    occupied = set().union(*(b.footprint.cells() for b in placed))
    if occupied & set(witness):
        return False
    return all(contact_cells(b, *pos[b.entity_id][:2]) & set(witness) for b in consumers)


def test_layers_match_bfs_parents():
    region = {(x, y) for x in range(8) for y in range(6)}
    roads = frozenset({(x, 2) for x in range(2, 8)} | {(5, y) for y in range(6)})
    pat = Pattern(th=Footprint(0, 1, 2, 2), roads=roads, params={})
    dist, parent = skeleton_layers(pat), skeleton_parents(pat)
    assert set(dist) == set(parent)
    for c, p in parent.items():
        assert dist[c] == (0 if p is None else dist[p] + 1)


def _fork():
    """TH at (1,1); roots (2,1) and (1,2); (2,2) is one layer out with BOTH
    roots as predecessors. BFS gives it parent (1,2). Two 1x1 slots: (3,1)
    touches only (2,1), (2,3) touches only (2,2). bfs needs 3 cells, layered 2."""
    roads = frozenset({(2, 1), (1, 2), (2, 2)})
    region = {(1, 1), *roads, (3, 1), (2, 3)}
    pat = Pattern(th=Footprint(1, 1, 1, 1), roads=roads, params={})
    consumers = [_b(10, 1, 1), _b(11, 1, 1)]
    hint = {10: (3, 1, 1, 1), 11: (2, 3, 1, 1)}
    return pat, region, consumers, hint


def test_layered_is_looser_than_bfs_on_a_cycle():
    pat, region, consumers, hint = _fork()
    assert skeleton_parents(pat)[(2, 2)] == (1, 2)
    got = {}
    for closure in CLOSURES:
        pos, diag = _solve(pat, region, consumers, hint, closure)
        assert pos is not None
        assert _witness_ok(pat, region, consumers, pos, diag["witness"])
        got[closure] = diag["objective"]
    assert got == {"bfs": 3, "layered": 2, "flow": 2}


def _ladder():
    """Two parallel rows from a 1x2 TH; slots only above the far end of the top
    row and below the far end of the bottom row. The cheapest network climbs
    across at the end -- a cell at the SAME distance, which layered forbids."""
    roads = frozenset({(x, y) for x in range(1, 6) for y in (1, 2)})
    region = {(0, 1), (0, 2), *roads, (5, 0), (5, 3)}
    pat = Pattern(th=Footprint(0, 1, 1, 2), roads=roads, params={})
    consumers = [_b(10, 1, 1), _b(11, 1, 1)]
    hint = {10: (5, 0, 1, 1), 11: (5, 3, 1, 1)}
    return pat, region, consumers, hint


def test_flow_is_exact_where_layered_is_not():
    pat, region, consumers, hint = _ladder()
    got = {}
    for closure in CLOSURES:
        pos, diag = _solve(pat, region, consumers, hint, closure)
        assert _witness_ok(pat, region, consumers, pos, diag["witness"])
        got[closure] = diag["objective"]
    assert got == {"bfs": 10, "layered": 10, "flow": 6}


def _random_case(rng):
    """A random cyclic skeleton (a lattice of full rows and columns joined to
    the TH, with some cells knocked out) and a feasible random placement."""
    W, H = 12, 10
    region = {(x, y) for x in range(W) for y in range(H)}
    th = Footprint(0, 0, 2, 2)
    rows = rng.sample(range(2, H), 2)
    cols = rng.sample(range(2, W), 2)
    roads = {(x, 2) for x in range(0, W)} | {(2, y) for y in range(0, H)}
    roads |= {(x, r) for r in rows for x in range(2, W)}
    roads |= {(c, y) for c in cols for y in range(2, H)}
    for c in rng.sample(sorted(roads), 4):
        roads.discard(c)
    roads -= th.cells()
    pat = Pattern(th=th, roads=frozenset(roads), params={})
    reach = set(skeleton_parents(pat))
    blocked = set(roads) | th.cells()
    consumers, hint, used = [], {}, set()
    spots = sorted(region)
    rng.shuffle(spots)
    for (x, y) in spots:
        if len(consumers) == 5:
            break
        w, l = rng.choice([(1, 1), (2, 1), (1, 2)])
        b = _b(10 + len(consumers), w, l)
        cells = Footprint(x, y, w, l).cells()
        if not cells <= region or cells & (blocked | used):
            continue
        if not contact_cells(b, x, y) & reach:
            continue
        used |= cells
        consumers.append(b)
        hint[b.entity_id] = (x, y, w, l)
    return pat, region, consumers, hint


def test_random_cyclic_patterns_are_connected_and_ordered():
    """Every closure's selection is a legal TH-connected network; when all
    three prove optimality, flow <= layered <= bfs (each is a relaxation of
    the previous on the same model)."""
    rng = random.Random(7)
    strict = 0
    for _ in range(12):
        pat, region, consumers, hint = _random_case(rng)
        got = {}
        for closure in CLOSURES:
            pos, diag = _solve(pat, region, consumers, hint, closure, limit=20.0)
            assert pos is not None
            assert _witness_ok(pat, region, consumers, pos, diag["witness"]), closure
            if diag["objective_status"] == "OPTIMAL":
                got[closure] = diag["objective"]
        if len(got) == 3:
            assert got["flow"] <= got["layered"] <= got["bfs"]
            strict += got["layered"] < got["bfs"]
    assert strict >= 1        # the cases really are cyclic enough to matter


def test_unknown_closure_is_rejected():
    pat, region, consumers, hint = _fork()
    with pytest.raises(ValueError):
        _solve(pat, region, consumers, hint, "dag")


# --- soft skeleton cells -------------------------------------------------------

def _corridor():
    region = set((x, y) for x in range(12) for y in range(5))
    th = Footprint(0, 1, 2, 2)
    roads = frozenset((x, 2) for x in range(2, 12))
    return region, Pattern(th=th, roads=roads, params={})


def test_soft_cells_let_a_building_sit_on_an_unused_skeleton_cell():
    """A 3x5 building spans the region's full height, so it must cover road
    cells: impossible on a hard skeleton, fine when unused cells are soft."""
    region, pat = _corridor()
    big = _b(10, 3, 5)
    hint = {10: (3, 0, 3, 5)}
    assert minimize_needed(pat, region, [big], hint, limit=5.0, model="position") is None
    for closure in CLOSURES:
        diag: dict = {}
        pos = minimize_needed(pat, region, [big], hint, limit=5.0, model="position",
                              soft=True, closure=closure, diag=diag)
        assert pos is not None and diag["objective"] == 1
        assert _witness_ok(pat, region, [big], pos, diag["witness"])
        th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
        lay = Layout(Region(frozenset(region)), [th, _b(10, 3, 5)], th, {})
        vst, out, n = validate(lay, pat, pos, witness=diag["witness"])
        assert vst == "OK" and n == 1 and check(out, lay).status == "valid"


def test_soft_is_never_worse_than_hard():
    rng = random.Random(11)
    for _ in range(6):
        pat, region, consumers, hint = _random_case(rng)
        hard, hd = _solve(pat, region, consumers, hint, "layered", limit=20.0)
        soft, sd = _solve(pat, region, consumers, hint, "layered", soft=True, limit=20.0)
        assert soft is not None
        assert _witness_ok(pat, region, consumers, soft, sd["witness"])
        if hd["objective_status"] == sd["objective_status"] == "OPTIMAL":
            assert sd["objective"] <= hd["objective"]


def test_soft_keeps_the_two_lane_tile_legal():
    region = frozenset((x, y) for x in range(14) for y in range(10))
    th = _b(1, 4, 4, needs=False, th=True, x=0, y=3)
    lay = Layout(Region(region), [th, _b(2, 3, 3, level=2), _b(3, 2, 2), _b(4, 2, 2)],
                 th, {})
    roads = frozenset((x, 7) for x in range(0, 12))
    pat = Pattern(th=th.footprint, roads=roads, params={})
    hint = {2: (5, 0, 3, 3), 3: (8, 8, 2, 2), 4: (10, 8, 2, 2), "lane2:0": (4, 4, 2, 2)}
    for closure in ("layered", "flow"):
        diag: dict = {}
        pos = minimize_needed(pat, set(region), lay.road_needing(), hint, limit=10.0,
                              model="position", soft=True, closure=closure, diag=diag)
        assert pos is not None
        vst, out, _ = validate(lay, pat, pos, witness=diag["witness"])
        assert vst == "OK" and check(out, lay).status == "valid", vst
