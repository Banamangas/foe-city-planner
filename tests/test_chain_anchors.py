"""N7: low-freedom composite chains are placed like the Townhall."""
import random
from types import SimpleNamespace

import pytest

from foeopt import roads_first as rf
from foeopt.chains import compose
from foeopt.model import Building, Footprint, Layout, Region

# An irregular region: a 22x3 strip on top of a 14x15 body. The 20x3 chain
# block fits only in the strip (x = 0, 1, 2 at y = 0).
STRIP = {(x, y) for x in range(22) for y in range(3)}
BODY = {(x, y) for x in range(14) for y in range(3, 18)}
REGION = STRIP | BODY


def _b(eid, x, y, w, l, needs=True, th=False, chain=None, links=()):
    return Building(eid, f"c{eid}", "main_building" if th else "g", Footprint(x, y, w, l),
                    needs, 1, th, None, chain, f"b{eid}", links)


def _city():
    """TH 4x4 in the body; a 4x3 head + four 4x3 linked pieces (20x3 block);
    two ordinary 2x2 consumers."""
    th = _b(1, 0, 10, 4, 4, needs=False, th=True)
    chain = [_b(10, 0, 0, 4, 3, chain="w", links=((4, 0, 7, 2),))]
    for i in range(4):
        chain.append(_b(11 + i, 4 + 4 * i, 0, 4, 3, needs=False, chain="w",
                        links=((4, 0, 7, 2),)))
    others = [_b(20, 8, 8, 2, 2), _b(21, 8, 12, 2, 2)]
    return compose(Layout(Region(frozenset(REGION)), [th, *chain, *others], th, {}))


def _composite(lay):
    return next(b for b in lay.buildings if b.members)


# ------------------------------------------------------------- anchor enumeration

def test_composite_anchors_on_an_irregular_region():
    assert rf.composite_anchors(REGION, 20, 3) == [(0, 0), (1, 0), (2, 0)]
    # a 4x4 fits the body only below the strip, and nowhere straddling x >= 14
    a = rf.composite_anchors(REGION, 4, 4)
    assert (0, 0) in a and (10, 14) in a and (11, 0) not in a and (14, 0) not in a
    # limit stops once the count exceeds it
    assert len(rf.composite_anchors(REGION, 4, 4, limit=5)) == 6


def test_chain_pins_selects_only_low_freedom_composites():
    lay = _city()
    comp = _composite(lay)
    pins = rf.chain_pins(set(REGION), lay.road_needing(), 50)
    assert [(p[0], p[1], p[2], p[3]) for p in pins] == [
        (comp.entity_id, 20, 3, [(0, 0), (1, 0), (2, 0)])]
    assert pins[0][4] == comp.contact
    assert rf.chain_pins(set(REGION), lay.road_needing(), 3) == []  # 3 is not < 3


def test_sample_pins_excludes_the_townhall_cells():
    lay = _city()
    pins = rf.chain_pins(set(REGION), lay.road_needing(), 50)
    th_on_strip = Footprint(0, 0, 4, 4).cells()       # covers x 0..3 of the strip
    assert rf._sample_pins(pins, th_on_strip, random.Random(0)) is None
    th_corner = Footprint(0, 0, 1, 1).cells()          # leaves only x = 1, 2
    seen = set()
    for s in range(20):
        (chosen, cut) = rf._sample_pins(pins, th_corner, random.Random(s))
        (_eid, x, y), = chosen
        seen.add((x, y))
        assert cut == Footprint(x, y, 20, 3).cells()
    assert seen == {(1, 0), (2, 0)}


# ------------------------------------------------------------- carve-out

def _gen(pins, seed=0, k=22, n=30):
    return rf.generate_nonuniform_patterns(set(REGION), 4, 4, k, random.Random(seed), n,
                                           th_mode="full", gaps=(3, 5), pins=pins)


def test_generator_carves_the_pinned_block_and_reaches_its_contact():
    lay = _city()
    comp = _composite(lay)
    pins = rf.chain_pins(set(REGION), lay.road_needing(), 50)
    pats = _gen(pins)
    assert pats
    for p in pats:
        (eid, x, y), = p.params["pins"]
        assert eid == comp.entity_id and (x, y) in pins[0][3]
        block = Footprint(x, y, 20, 3).cells()
        assert not (p.roads & block) and not (p.th.cells() & block)
        assert any((x + dx, y + dy) in p.roads for dx, dy in comp.contact)
        rf._check_pattern(p, set(REGION), 22)   # connected to the TH, k cells


def test_generator_is_deterministic_with_pins():
    lay = _city()
    pins = rf.chain_pins(set(REGION), lay.road_needing(), 50)
    a, b = _gen(pins, seed=3), _gen(pins, seed=3)
    assert [(p.th, p.roads, p.params) for p in a] == [(p.th, p.roads, p.params) for p in b]


def test_generator_without_pins_is_unchanged():
    base = rf.generate_nonuniform_patterns(set(REGION), 4, 4, 22, random.Random(5), 30,
                                           th_mode="full", gaps=(3, 5))
    for pins in (None, []):
        got = _gen(pins, seed=5)
        assert [(p.th, p.roads, p.params) for p in got] == \
               [(p.th, p.roads, p.params) for p in base]
    assert all("pins" not in p.params for p in base)


# ------------------------------------------------------------- the fix in the model

def _skeleton(lay):
    # a column at x = 4 from the TH (y = 10) up to the strip; touches the head's
    # bottom edge at (4, 3) only when the block sits at x >= 1
    return frozenset({(4, y) for y in range(3, 11)})


@pytest.mark.parametrize("x", [1, 2])
def test_position_model_fixes_the_composite_at_its_pin(x):
    lay = _city()
    comp = _composite(lay)
    pat = rf.Pattern(th=lay.townhall.footprint, roads=_skeleton(lay),
                     params={"pins": ((comp.entity_id, x, 0),)})
    st, pos = rf.probe(pat, set(REGION), lay.road_needing(), probe_limit=10,
                       model="position")
    assert st == "SAT" and pos[comp.entity_id][:2] == (x, 0)


def test_pin_without_road_contact_is_unsat():
    lay = _city()
    comp = _composite(lay)
    roads = _skeleton(lay)
    free = rf.Pattern(th=lay.townhall.footprint, roads=roads, params={})
    assert rf.probe(free, set(REGION), lay.road_needing(), probe_limit=10,
                    model="position")[0] == "SAT"
    pinned = rf.Pattern(th=lay.townhall.footprint, roads=roads,
                        params={"pins": ((comp.entity_id, 0, 0),)})
    diag = {}
    st, _ = rf.probe(pinned, set(REGION), lay.road_needing(), probe_limit=10,
                     model="position", diag=diag)
    assert st == "UNSAT" and diag["reason"] == "no_anchor"


# ------------------------------------------------------------- option wiring

def _levels(lay, **extra):
    params = SimpleNamespace(patterns=20, th_anchors="full", pattern_family="nonuniform",
                             quality_index_band=None, **extra)
    st = rf._generate_levels(lay, set(REGION), lay.road_needing(), [40, 41],
                             random.Random(0), params, lambda row: None)
    return {k: [(p.th, p.roads, p.params) for p in v["pats"]] for k, v in st.items()}


def test_off_by_default_is_identical():
    lay = _city()
    base = _levels(lay)
    assert _levels(lay, chain_anchors=0) == base
    assert _levels(lay, chain_anchors=2) == base     # 3 anchors: not low-freedom
    on = _levels(lay, chain_anchors=50)
    assert on != base and all("pins" in p for v in on.values() for _, _, p in v)


def test_search_option_default_and_validation():
    lay = _city()
    assert rf.RoadsFirstSearch(lay, time_box=1.0).chain_anchors == 0
    with pytest.raises(ValueError):
        rf.RoadsFirstSearch(lay, time_box=1.0, chain_anchors=50, pattern_family="comb")
    rf.RoadsFirstSearch(lay, time_box=1.0, chain_anchors=50, pattern_family="nonuniform")
