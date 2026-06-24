import random

from foeopt.model import Building, Footprint, Layout, Region
from rl.curriculum import make_real_like_city


def _reference():
    # a small irregular-region stand-in for darkzig with a TH + a few buildings
    cells = frozenset((x, y) for x in range(10) for y in range(8)) | \
            frozenset((x, y) for x in range(10, 14) for y in range(4, 8))   # L-shaped
    th = Building(1, "c1", "main_building", Footprint(1, 1, 3, 2),
                  False, 1, True, None, None, "TH")
    mix = [Building(10, "c10", "g", Footprint(0, 0, 4, 4), True, 1, False, None, None, "a"),
           Building(11, "c11", "g", Footprint(0, 0, 2, 3), True, 1, False, None, None, "b"),
           Building(12, "c12", "g", Footprint(0, 0, 5, 5), False, 1, False, None, None, "c")]
    return Layout(Region(cells), [th, *mix], th, {})


def test_real_like_city_keeps_reference_region_and_townhall():
    ref = _reference()
    city = make_real_like_city(random.Random(0), ref)
    assert city.region.cells == ref.region.cells
    assert city.townhall is ref.townhall                  # same TH object/position


def test_real_like_city_buildings_at_origin_for_env_to_reposition():
    ref = _reference()
    city = make_real_like_city(random.Random(0), ref)
    for b in city.buildings:
        if not b.is_townhall:
            assert (b.footprint.x, b.footprint.y) == (0, 0)


def test_real_like_city_fill_approximates_target():
    ref = _reference()
    city = make_real_like_city(random.Random(0), ref, fill=0.9)
    region_area = len(ref.region.cells)
    th_area = ref.townhall.footprint.width * ref.townhall.footprint.length
    bld_area = sum(b.footprint.width * b.footprint.length for b in city.buildings)
    assert th_area <= bld_area <= 0.95 * region_area      # ~90% fill, tolerance
    assert bld_area >= 0.8 * region_area


def test_real_like_city_is_deterministic_given_seed():
    ref = _reference()
    c1 = make_real_like_city(random.Random(7), ref)
    c2 = make_real_like_city(random.Random(7), ref)
    assert [(b.footprint.width, b.footprint.length, b.needs_road) for b in c1.buildings] == \
           [(b.footprint.width, b.footprint.length, b.needs_road) for b in c2.buildings]
