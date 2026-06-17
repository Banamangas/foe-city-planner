from foeopt.catalog import Catalog


def test_size_top_level(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    # Townhall has top-level width/length 6x7
    assert cat.size("H_SpaceAgeSpaceHub_Townhall") == (6, 7)


def test_size_from_placement_component(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    # Multi-age building: size only in components.<Age>.placement.size
    assert cat.size("W_MultiAge_WIN24F4") == (1, 2)


def test_required_level_defaults_to_one(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    # event building with no street_connection_level -> default 1
    assert cat.required_level("W_MultiAge_WIN24F4") == 1
    # Townhall explicitly level 1
    assert cat.required_level("H_SpaceAgeSpaceHub_Townhall") == 1


def test_provided_level_for_street(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    assert cat.provided_level("S_SpaceAgeSpaceHub_Street1") == 1


def test_name_present(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    assert isinstance(cat.name("H_SpaceAgeSpaceHub_Townhall"), str)
    assert cat.name("H_SpaceAgeSpaceHub_Townhall") != ""
