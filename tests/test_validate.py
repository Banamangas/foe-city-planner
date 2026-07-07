from foeopt.model import Building, Footprint, Layout, Region
from foeopt.validate import connected_road_cells, unsatisfied, is_valid


def _th(x, y):
    return Building(1, "TH", "main_building", Footprint(x, y, 1, 1),
                    needs_road=True, road_level=1, is_townhall=True,
                    set_id=None, chain_id=None, name="Townhall")


def _house(eid, x, y, level=1):
    return Building(eid, "H", "generic_building", Footprint(x, y, 1, 1),
                    needs_road=True, road_level=level, is_townhall=False,
                    set_id=None, chain_id=None, name="House")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_connected_chain_from_townhall():
    # TH at (0,0); roads at (1,0),(2,0); house at (3,0) adjacent to road (2,0)
    layout = Layout(_region(5, 1), [_th(0, 0), _house(2, 3, 0)],
                    _th(0, 0), roads={(1, 0): 1, (2, 0): 1})
    assert connected_road_cells(layout) == {(1, 0), (2, 0)}
    assert unsatisfied(layout) == []
    assert is_valid(layout)


def test_townhall_adjacency_is_not_enough():
    # house touches the townhall but there is no road -> unsatisfied
    layout = Layout(_region(3, 1), [_th(0, 0), _house(2, 1, 0)],
                    _th(0, 0), roads={})
    assert [b.entity_id for b in unsatisfied(layout)] == [2]
    assert not is_valid(layout)


def test_road_island_not_connected_to_townhall():
    # roads at (3,0),(4,0) serve the house but a gap at (1,0),(2,0) leaves them
    # disconnected from the townhall at (0,0). House is at x=5.
    layout = Layout(_region(6, 1), [_th(0, 0), _house(2, 5, 0)],
                    _th(0, 0), roads={(3, 0): 1, (4, 0): 1})
    assert connected_road_cells(layout) == set()
    assert [b.entity_id for b in unsatisfied(layout)] == [2]


def test_level_requirement_enforced():
    # house needs level 2 but only a level-1 road is adjacent
    layout = Layout(_region(4, 1), [_th(0, 0), _house(2, 2, 0, level=2)],
                    _th(0, 0), roads={(1, 0): 1})
    assert [b.entity_id for b in unsatisfied(layout)] == [2]
    # upgrade the road to level 2 -> satisfied
    layout.roads[(1, 0)] = 2
    assert unsatisfied(layout) == []


def test_current_real_layout_is_valid(city_data, helper_data):
    from foeopt.build import build_layout
    layout = build_layout(city_data, helper_data)
    assert is_valid(layout), [b.name for b in unsatisfied(layout)][:5]


def test_isolated_th_stub_road_is_valid():
    # TH-stub load-bearing regression (THT-A): a single road cell whose only
    # connection to the network is via Townhall-border adjacency (no other
    # road cell neighbors it) must still validate. TH 2x2 at (1,1); the stub
    # road cell (3,1) borders TH cell (2,1) directly; a 2x2 consumer at (4,0)
    # has (3,1) on its border. Roads = exactly {(3,1): 1}.
    th = Building(1, "TH", "main_building", Footprint(1, 1, 2, 2),
                 needs_road=True, road_level=1, is_townhall=True,
                 set_id=None, chain_id=None, name="Townhall")
    consumer = Building(2, "C", "generic_building", Footprint(4, 0, 2, 2),
                        needs_road=True, road_level=1, is_townhall=False,
                        set_id=None, chain_id=None, name="Consumer")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, consumer], th, roads={(3, 1): 1})
    assert is_valid(layout)


# --- orientation / no-rotation guard (FoE buildings cannot rotate) ---
from foeopt.validate import canonical_dims, rotated_buildings


def _rect(eid, x, y, w, l, *, th=False):
    return Building(eid, "R", "main_building" if th else "generic_building",
                    Footprint(x, y, w, l), needs_road=not th, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name="R")


def test_canonical_dims_extracts_ordered_wl_by_entity_id():
    ref = Layout(_region(20, 20),
                 [_rect(1, 0, 0, 2, 2, th=True), _rect(10, 4, 0, 6, 4),
                  _rect(11, 0, 4, 4, 3)],
                 _rect(1, 0, 0, 2, 2, th=True), roads={})
    assert canonical_dims(ref) == {1: (2, 2), 10: (6, 4), 11: (4, 3)}


def test_rotated_buildings_empty_when_all_match_canonical():
    ref = Layout(_region(20, 20), [_rect(10, 4, 0, 6, 4)], None, roads={})
    canon = canonical_dims(ref)
    same = Layout(_region(20, 20), [_rect(10, 9, 9, 6, 4)], None, roads={})  # moved, not rotated
    assert rotated_buildings(same, canon) == []


def test_rotated_buildings_flags_swapped_wl():
    canon = {10: (6, 4), 11: (4, 3)}
    lay = Layout(_region(20, 20),
                 [_rect(10, 0, 0, 6, 4),   # canonical -> ok
                  _rect(11, 0, 6, 3, 4)],  # 4x3 placed as 3x4 -> ROTATED
                 None, roads={})
    flagged = [b.entity_id for b in rotated_buildings(lay, canon)]
    assert flagged == [11]


def test_rotated_buildings_ignores_squares():
    canon = {10: (2, 2)}
    lay = Layout(_region(9, 9), [_rect(10, 0, 0, 2, 2)], None, roads={})
    assert rotated_buildings(lay, canon) == []


def test_rotated_buildings_skips_unknown_ids():
    # a building absent from the canonical map is not flagged (defensive)
    lay = Layout(_region(9, 9), [_rect(99, 0, 0, 3, 2)], None, roads={})
    assert rotated_buildings(lay, {}) == []
