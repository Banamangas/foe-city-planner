from foeopt.build import build_layout
from foeopt.router import route
from foeopt.validate import is_valid
from foeopt.report import stats


def test_phase1_reduces_roads_on_real_city(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    optimized = route(layout)
    probe_layout = build_layout(city_data, helper_data)
    probe_layout.roads = optimized
    # every road-needing building is connected to the townhall
    assert is_valid(probe_layout)
    s = stats(layout, optimized)
    assert s["unsatisfied"] == 0
    # the optimizer must not be worse than the current 142 roads
    assert s["optimized_roads"] <= s["current_roads"]
    print(s)
