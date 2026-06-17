import foeopt


def test_package_imports():
    assert hasattr(foeopt, "__version__")


def test_fixtures_load(city_data, helper_data):
    assert city_data["__class__"] == "CityMap"
    assert "CityEntities" in helper_data
