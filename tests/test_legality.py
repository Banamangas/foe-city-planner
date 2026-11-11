"""foeopt.legality: the full game-rule gate (two-lane tiles, chains, inventory)."""
from dataclasses import replace

import pytest

from foeopt.legality import chain_links, check, two_lane_tiles
from foeopt.model import Building, Footprint, Layout, Region

REGION = Region(frozenset((x, y) for x in range(20) for y in range(12)))


def _b(eid, x, y, w, l, needs=True, level=1, th=False, chain=None, links=()):
    return Building(eid, f"c{eid}", "main_building" if th else "g", Footprint(x, y, w, l),
                    needs, level, th, None, chain, f"b{eid}", links)


def _lay(buildings, roads):
    th = next(b for b in buildings if b.is_townhall)
    return Layout(REGION, list(buildings), th, dict(roads))


def _military_city(tile_xy, mil_xy=(4, 6)):
    """TH 4x4 at (0,0); a 2x2 two-lane tile; a 3x3 level-2 military building."""
    th = _b(1, 0, 0, 4, 4, needs=False, th=True)
    mil = _b(2, *mil_xy, 3, 3, level=2)
    tx, ty = tile_xy
    roads = {(tx + dx, ty + dy): 2 for dx in (0, 1) for dy in (0, 1)}
    return _lay([th, mil], roads)


def test_input_style_single_tile_between_th_and_military_is_valid():
    # tile (3,4)-(4,5) touches the TH's bottom edge and the military's top edge
    # (darkzig's real input does exactly this with one tile).
    lay = _military_city((3, 4))
    assert check(lay, lay).status == "valid"


def test_two_lane_building_on_a_one_lane_path_is_invalid():
    th = _b(1, 0, 0, 4, 4, needs=False, th=True)
    mil = _b(2, 8, 0, 3, 3, level=2)
    roads = {(x, 1): 1 for x in range(4, 6)}
    roads.update({(x, y): 2 for x in (6, 7) for y in (0, 1)})  # 2x2 tile, but via 1-lane
    lay = _lay([th, mil], roads)
    rep = check(lay, lay)
    assert [v["rule"] for v in rep.violations] == ["two_lane_path"]
    assert check(lay, lay, military="unconnected").status == "valid"


def test_single_level2_cell_is_not_a_tile():
    th = _b(1, 0, 0, 4, 4, needs=False, th=True)
    mil = _b(2, 5, 0, 3, 3, level=2)
    lay = _lay([th, mil], {(4, 0): 2})  # what route() writes today: a 1x1 "two-lane"
    rules = {v["rule"] for v in check(lay, lay).violations}
    assert "two_lane_not_2x2" in rules


def test_two_lane_tiles_partition():
    sq = {(x, y): 2 for x in (0, 1) for y in (0, 1)}
    assert two_lane_tiles(sq) == [(0, 0)]
    two = {**sq, **{(x, y): 2 for x in (2, 3) for y in (1, 2)}}  # offset neighbour
    assert two_lane_tiles(two) == [(0, 0), (2, 1)]
    assert two_lane_tiles({**sq, (2, 0): 2}) is None


def _chain_city(gap=0):
    """Statue 4x3 linking right (x+4..5) to a 2x3 piece that links right again."""
    th = _b(1, 0, 6, 4, 4, needs=False, th=True)
    statue = _b(10, 0, 0, 4, 3, chain="rtv", links=((4, 0, 5, 2),))
    p1 = _b(11, 4 + gap, 0, 2, 3, needs=False, chain="rtv", links=((2, 0, 3, 2),))
    p2 = _b(12, 6 + gap, 0, 2, 3, needs=False, chain="rtv", links=((2, 0, 3, 2),))
    return _lay([th, statue, p1, p2], {(x, 3): 1 for x in range(0, 4)} | {(0, 4): 1, (0, 5): 1})


def test_straight_chain_links_are_detected_and_preserved():
    ref = _chain_city()
    assert chain_links(ref) == {(10, 11), (11, 12)}
    assert check(ref, ref).status == "valid"


def test_chain_offset_by_one_is_broken():
    ref = _chain_city()
    moved = _chain_city(gap=1)
    rep = check(moved, ref)
    assert rep.violations == [{"rule": "chain_broken", "links": [(10, 11)]}]


def test_behind_linked_chain():
    th = _b(1, 0, 6, 4, 4, needs=False, th=True)
    statue = _b(10, 5, 3, 2, 3, chain="serpent", links=((0, -2, 1, -1),))
    piece = _b(11, 5, 1, 2, 2, needs=False, chain="serpent")
    lay = _lay([th, statue, piece], {(4, y): 1 for y in range(3, 7)})
    assert chain_links(lay) == {(10, 11)}
    shifted = _lay([th, statue, replace(piece, footprint=Footprint(7, 3, 2, 2))],
                   {(4, y): 1 for y in range(3, 7)})
    assert check(shifted, lay).status == "invalid"


def test_missing_catalog_is_unknown_not_valid():
    ref = _chain_city()
    ref.catalog_known = False
    rep = check(ref, ref)
    assert rep.status == "unknown" and not rep.ok


def test_inventory_rotation_overlap_and_road_cells():
    ref = _chain_city()
    th, statue, p1, p2 = ref.buildings
    rotated = _lay([th, replace(statue, footprint=Footprint(0, 0, 3, 4)), p1, p2], ref.roads)
    assert "rotated" in {v["rule"] for v in check(rotated, ref).violations}
    dropped = _lay([th, statue, p1], ref.roads)
    assert "inventory" in {v["rule"] for v in check(dropped, ref).violations}
    on_road = _lay(ref.buildings, {**ref.roads, (5, 1): 1})
    assert "on_road" in {v["rule"] for v in check(on_road, ref).violations}


def test_unknown_military_policy_rejected():
    ref = _chain_city()
    with pytest.raises(ValueError):
        check(ref, ref, military="maybe")
