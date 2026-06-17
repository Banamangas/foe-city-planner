from foeopt.build import build_layout


def test_build_layout_counts(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    # 142 streets currently
    assert len(layout.roads) == 142
    # all in-region buildings (anchor inside the unlocked region)
    assert len(layout.buildings) == 292
    # townhall identified
    assert layout.townhall is not None
    assert layout.townhall.is_townhall
    assert layout.townhall.cityentity_id == "H_SpaceAgeSpaceHub_Townhall"
    # 81 road-needing (incl. townhall) -> 80 consumers via road_needing()
    needing_incl_th = [b for b in layout.buildings if b.needs_road]
    assert len(needing_incl_th) == 81
    assert len(layout.road_needing()) == 80


def test_offgrid_excluded_by_region(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    cids = {b.cityentity_id for b in layout.buildings}
    # settlement hubs sit outside the region -> excluded
    assert "O_OceanicFuture_Hub1" not in cids
    assert "O_ArcticFuture_Hub1" not in cids
    # every kept building's anchor is inside the buildable region
    for b in layout.buildings:
        assert (b.footprint.x, b.footprint.y) in layout.region.cells


def test_yukitomo_not_road_needing(city_data, helper_data):
    # Yukitomo residences carry the `connected` key but no adjacent road -> not road-needing
    layout = build_layout(city_data, helper_data)
    yuki = [b for b in layout.buildings
            if b.cityentity_id in {"W_MultiAge_WIN24A13", "W_MultiAge_WIN24A14"}]
    assert yuki  # present in the city
    assert all(not b.needs_road for b in yuki)


def test_every_building_has_size(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    for b in layout.buildings:
        assert b.footprint.width > 0 and b.footprint.length > 0
