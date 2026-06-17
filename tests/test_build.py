from foeopt.build import build_layout


def test_build_layout_counts(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    # 142 streets currently
    assert len(layout.roads) == 142
    # townhall identified
    assert layout.townhall is not None
    assert layout.townhall.is_townhall
    assert layout.townhall.cityentity_id == "H_SpaceAgeSpaceHub_Townhall"
    # 99 road-needing buildings (incl. townhall) -> 98 consumers via road_needing()
    needing_incl_th = [b for b in layout.buildings if b.needs_road]
    assert len(needing_incl_th) == 99
    assert len(layout.road_needing()) == 98


def test_build_layout_excludes_offgrid(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    for b in layout.buildings:
        assert b.type not in {"off_grid", "outpost_ship", "friends_tavern"}
        for (cx, cy) in b.footprint.cells():
            assert 0 <= cx < 200 and 0 <= cy < 200


def test_every_building_has_size(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    for b in layout.buildings:
        assert b.footprint.width > 0 and b.footprint.length > 0
