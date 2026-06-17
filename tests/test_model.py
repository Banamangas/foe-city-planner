from foeopt.model import Footprint, Building, Region, Layout


def test_footprint_cells_and_border():
    fp = Footprint(x=2, y=3, width=2, length=1)
    assert fp.cells() == {(2, 3), (3, 3)}
    # orthogonal neighbours of the two cells, excluding the footprint itself
    assert fp.border_cells() == {
        (1, 3), (4, 3),          # left / right
        (2, 2), (3, 2),          # above
        (2, 4), (3, 4),          # below
    }


def test_region_contains():
    region = Region(cells=frozenset({(0, 0), (1, 0), (0, 1), (1, 1)}))
    assert region.contains_cell((0, 0))
    assert not region.contains_cell((2, 0))
    assert region.contains_footprint(Footprint(0, 0, 2, 1))
    assert not region.contains_footprint(Footprint(0, 0, 3, 1))


def test_layout_helpers():
    th = Building(1, "TH", "main_building", Footprint(0, 0, 1, 1),
                  needs_road=True, road_level=1, is_townhall=True,
                  set_id=None, chain_id=None, name="Townhall")
    house = Building(2, "H", "generic_building", Footprint(2, 0, 1, 1),
                     needs_road=True, road_level=1, is_townhall=False,
                     set_id=None, chain_id=None, name="House")
    deco = Building(3, "D", "generic_building", Footprint(4, 0, 1, 1),
                    needs_road=False, road_level=0, is_townhall=False,
                    set_id=None, chain_id=None, name="Deco")
    layout = Layout(Region(frozenset()), [th, house, deco], th, roads={})
    assert layout.occupied_cells() == {(0, 0), (2, 0), (4, 0)}
    # townhall is excluded from road_needing (it is the root, not a consumer)
    assert layout.road_needing() == [house]
