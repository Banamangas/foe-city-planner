from foeopt.region import build_region


def test_build_region_unions_rectangles():
    areas = [
        {"x": 0, "y": 0, "width": 2, "length": 2},
        {"x": 2, "y": 0, "width": 1, "length": 1},  # note: x present, no y means y=0
    ]
    region = build_region(areas)
    assert region.cells == frozenset(
        {(0, 0), (1, 0), (0, 1), (1, 1), (2, 0)}
    )


def test_build_region_handles_missing_coords():
    # FoE omits x or y when they are 0
    areas = [{"width": 1, "length": 1}]  # implies x=0, y=0
    region = build_region(areas)
    assert region.cells == frozenset({(0, 0)})


def test_real_region_size(city_data):
    region = build_region(city_data["unlocked_areas"])
    assert len(region.cells) == 4224
