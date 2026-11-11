"""foeopt.chains: linked chains placed as rigid composites."""
from foeopt.chains import compose, expand, linked_groups, make_composite
from foeopt.legality import chain_links, check
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern, _anchor_candidates, _size_classes, validate

REGION = Region(frozenset((x, y) for x in range(20) for y in range(12)))


def _b(eid, x, y, w, l, needs=True, th=False, chain=None, links=()):
    return Building(eid, f"c{eid}", "main_building" if th else "g", Footprint(x, y, w, l),
                    needs, 1, th, None, chain, f"b{eid}", links)


def _city():
    th = _b(1, 0, 8, 4, 4, needs=False, th=True)
    statue = _b(10, 0, 0, 4, 3, chain="rtv", links=((4, 0, 5, 2),))
    p1 = _b(11, 4, 0, 2, 3, needs=False, chain="rtv", links=((2, 0, 3, 2),))
    p2 = _b(12, 6, 0, 2, 3, needs=False, chain="rtv", links=((2, 0, 3, 2),))
    other = _b(20, 10, 0, 2, 2)
    return Layout(REGION, [th, statue, p1, p2, other], th, {})


def test_compose_makes_one_rigid_block_with_the_statue_edge_as_contact():
    lay = compose(_city())
    comp = [b for b in lay.buildings if b.members]
    assert len(comp) == 1 and len(lay.buildings) == 3
    c = comp[0]
    assert (c.footprint.width, c.footprint.length) == (8, 3) and c.needs_road
    # contact = the statue's border only: x=-1 column, rows -1 and 3 for x 0..3
    assert (-1, 1) in c.contact and (2, 3) in c.contact and (2, -1) in c.contact
    assert (5, 3) not in c.contact and (8, 1) not in c.contact


def test_expand_restores_members_at_their_offsets():
    src = _city()
    lay = compose(src)
    moved = [b for b in lay.buildings if b.members][0]
    moved.footprint = Footprint(5, 4, 8, 3)
    out = expand(lay)
    pos = {b.entity_id: (b.footprint.x, b.footprint.y) for b in out.buildings}
    assert pos[10] == (5, 4) and pos[11] == (9, 4) and pos[12] == (11, 4)
    assert chain_links(out) == chain_links(src)


def test_anchor_requires_a_road_on_the_statue_edge_not_on_a_link():
    lay = compose(_city())
    c = [b for b in lay.buildings if b.members][0]
    region = set(REGION.cells)
    road_under_link = frozenset({(6, 3)})   # below piece 1 if anchored at (0,0)
    opts = _anchor_candidates(c, region, set(road_under_link), road_under_link)
    assert (0, 0) not in opts
    road_under_statue = frozenset({(1, 3)})
    assert (0, 0) in _anchor_candidates(c, region, set(road_under_statue), road_under_statue)


def test_same_size_different_contact_are_different_classes():
    a = _b(1, 0, 0, 2, 2)
    b = _b(2, 0, 0, 2, 2)
    b.contact = frozenset({(-1, 0)})
    assert len(_size_classes([a, b])) == 2


def test_not_composed_when_holes_or_two_road_members():
    s = _b(10, 0, 0, 4, 3, chain="x", links=((4, 0, 5, 1),))
    p = _b(11, 4, 0, 2, 2, needs=False, chain="x")       # leaves a hole at (4..5, 2)
    assert make_composite([s, p]) is None
    s2 = _b(10, 0, 0, 4, 3, chain="x", links=((4, 0, 5, 2),))
    p2 = _b(11, 4, 0, 2, 3, needs=True, chain="x")
    assert make_composite([s2, p2]) is None


def test_validate_emits_real_members_with_links_intact():
    src = _city()
    lay = compose(src)
    th = lay.townhall
    # skeleton: a road column at x=4 from the TH (y=8) up to y=3, then along y=3
    roads = frozenset({(4, y) for y in range(3, 9)} | {(x, 3) for x in range(0, 4)})
    pat = Pattern(th=th.footprint, roads=roads, params={})
    comp = [b for b in lay.buildings if b.members][0]
    positions = {comp.entity_id: (0, 0, 8, 3), 20: (5, 4, 2, 2)}
    st, out, n = validate(lay, pat, positions)
    assert st == "OK", st
    assert sorted(b.entity_id for b in out.buildings) == [1, 10, 11, 12, 20]
    assert check(out, src).status == "valid"
    assert linked_groups(out) and len(linked_groups(out)[0]) == 3
