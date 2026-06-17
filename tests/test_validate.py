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
