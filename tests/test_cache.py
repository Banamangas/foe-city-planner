import json
import pytest

from webapp.cache import CityCache


@pytest.fixture()
def cache():
    c = CityCache(":memory:")
    yield c
    c.close()


def test_store_and_get_city(cache):
    payload = json.dumps({"CityMapData": {}, "UnlockedAreas": [], "CityEntities": {}}).encode()
    cache.store_city("abc123", payload, [{"name": "TH", "is_townhall": True}], 100, 50)
    city = cache.get_city("abc123")
    assert city is not None
    assert city["id"] == "abc123"
    assert city["region_cells"] == 100
    assert city["road_estimate"] == 50
    assert len(city["buildings"]) == 1
    assert city["buildings"][0]["name"] == "TH"
    assert isinstance(city["payload"], dict)


def test_get_city_returns_none_if_not_found(cache):
    assert cache.get_city("nonexistent") is None


def test_list_cities(cache):
    payload = b'{}'
    cache.store_city("city1", payload, [], 50, 25)
    cache.store_city("city2", payload, [], 100, 50)
    cities = cache.list_cities()
    assert len(cities) == 2
    ids = {c["id"] for c in cities}
    assert ids == {"city1", "city2"}


def test_store_and_get_layout(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    layout_data = {"k": 92, "achieved": 79, "roads": [[0, 1]], "buildings": {"1": [0, 0, 2, 2]}}
    cache.store_layout("lay1", "city1", 92, 79, layout_data, 79)
    lay = cache.get_layout("lay1")
    assert lay is not None
    assert lay["id"] == "lay1"
    assert lay["city_id"] == "city1"
    assert lay["k"] == 92
    assert lay["achieved"] == 79
    assert lay["roads_count"] == 79
    assert isinstance(lay["layout"], dict)
    assert lay["layout"]["k"] == 92


def test_list_layouts_by_city(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    cache.store_city("city2", b'{}', [], 100, 50)
    cache.store_layout("lay1", "city1", 92, 79, {}, 79)
    cache.store_layout("lay2", "city1", 88, 85, {}, 85)
    cache.store_layout("lay3", "city2", 100, 95, {}, 95)
    layouts = cache.list_layouts(city_id="city1")
    assert len(layouts) == 2
    for l in layouts:
        assert l["city_id"] == "city1"


def test_list_all_layouts(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    cache.store_layout("lay1", "city1", 92, 79, {}, 79)
    cache.store_layout("lay2", "city1", 88, 85, {}, 85)
    layouts = cache.list_layouts()
    assert len(layouts) == 2


def test_delete_layout(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    cache.store_layout("lay1", "city1", 92, 79, {}, 79)
    assert cache.delete_layout("lay1") is True
    assert cache.get_layout("lay1") is None
    assert cache.delete_layout("lay1") is False


def test_store_city_is_idempotent(cache):
    payload1 = b'{"v": 1}'
    payload2 = b'{"v": 2}'
    cache.store_city("city1", payload1, [], 50, 25)
    cache.store_city("city1", payload2, [], 100, 50)
    city = cache.get_city("city1")
    assert city["region_cells"] == 100
