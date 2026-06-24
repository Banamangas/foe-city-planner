from foeopt.model import Building, Footprint, Layout, Region
from rl.oracle import optimal_roads


def _layout(buildings):
    th = next(b for b in buildings if b.is_townhall)
    return Layout(Region(frozenset((x, y) for x in range(12) for y in range(12))),
                  buildings, th, {})


def _b(eid, w, l, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(0, 0, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def test_oracle_finds_one_road_for_single_consumer_next_to_th():
    # TH 1x1 at (0,0); one 1x1 consumer -> optimum is 1 road.
    layout = _layout([_b(1, 1, 1, needs=False, th=True), _b(10, 1, 1, needs=True)])
    assert optimal_roads(layout) == 1


def test_oracle_matches_trivial_zero_when_no_road_needing():
    layout = _layout([_b(1, 1, 1, needs=False, th=True), _b(10, 2, 2, needs=False)])
    assert optimal_roads(layout) == 0      # no road-needing building -> 0 roads


def test_oracle_refuses_too_many_buildings():
    layout = _layout([_b(1, 1, 1, needs=False, th=True)] +
                    [_b(10 + i, 1, 1, needs=True) for i in range(5)])
    try:
        optimal_roads(layout)
        assert False, "should have raised for >4 non-TH buildings"
    except ValueError:
        pass