from foeopt.build import build_layout
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.viz import (
    COLOR_PLAIN_BUILDING,
    COLOR_REGION,
    render_html,
)
from foeopt.viz import render_comparison


def test_render_comparison_embeds_both_layouts(city_data, helper_data):
    from foeopt.build import build_layout
    from foeopt.packer import repack
    current = build_layout(city_data, helper_data)
    optimized = repack(current, budget_seconds=0.3).layout
    html = render_comparison(current, optimized)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "http://" not in html and "https://" not in html
    # a view toggle is present
    assert "current" in html and "optimized" in html
    # both building sets are embedded (data-name hover metadata present)
    assert "data-name" in html


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = hexcolor.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def test_plain_building_contrasts_with_region():
    """Regression: non-road buildings must be clearly distinguishable from the
    region background. The original #555 building on #3a3a3a region had a
    channel-sum distance of only 81 and read as 'missing' on the map."""
    distance = sum(abs(a - b) for a, b in zip(_rgb(COLOR_PLAIN_BUILDING), _rgb(COLOR_REGION)))
    assert distance >= 150, (
        f"plain building {COLOR_PLAIN_BUILDING} too close to region "
        f"{COLOR_REGION} (distance {distance})"
    )


def test_render_html_is_self_contained(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    html = render_html(layout)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    # no external resources
    assert "http://" not in html and "https://" not in html
    # building metadata embedded for hover
    assert "data-name" in html
    assert "data-size" in html
    # townhall name appears
    assert "tel de ville" in html or "Townhall" in html


def test_render_html_marks_optimized_roads(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    html = render_html(layout, optimized_roads={(7, 60): 1})
    assert "optimized" in html


def test_render_html_ampersand_not_escaped():
    """Regression test: building names with & must not be HTML-entity-escaped in JSON."""
    footprint = Footprint(0, 0, 1, 1)
    building = Building(
        entity_id=1,
        cityentity_id="b1",
        type="generic",
        footprint=footprint,
        needs_road=False,
        road_level=0,
        is_townhall=False,
        set_id=None,
        chain_id=None,
        name="Forge & Anvil",
    )
    region = Region(frozenset({(0, 0)}))
    layout = Layout(region=region, buildings=[building], townhall=None)

    html = render_html(layout)

    # The raw building name must appear unescaped in the JSON output
    assert "Forge & Anvil" in html
    # It must NOT be escaped as &amp;
    assert "Forge &amp; Anvil" not in html


def test_layout_to_view_returns_dict_with_required_keys():
    from foeopt.viz import layout_to_view
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    b1 = Building(10, "c10", "g", Footprint(3, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, b1], th, {(0, 2): 1})
    view = layout_to_view(lay)
    assert isinstance(view, dict)
    assert view["cell"] == 12
    assert "width" in view and "height" in view
    assert isinstance(view["region"], list)
    assert len(view["buildings"]) == 2
    assert view["buildings"][0]["name"] in ("TH", "a")
    assert isinstance(view["current_roads"], list)
    assert view["optimized_roads"] is None
    assert "palette" in view
    for key in ("background", "region", "current_road", "optimized_road",
                "townhall", "road_building", "plain_building", "border"):
        assert key in view["palette"]


def test_layout_to_view_with_optimized_roads():
    from foeopt.viz import layout_to_view
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th], th, {(0, 2): 1})
    opt = {(3, 0): 1}
    view = layout_to_view(lay, optimized_roads=opt)
    assert view["optimized_roads"] is not None
    assert len(view["optimized_roads"]) == 1
    assert view["optimized_roads"][0]["level"] == 1


def test_layout_to_view_includes_grid_origin():
    from foeopt.viz import layout_to_view
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(3, 5, 2, 2),
                  False, 1, True, None, None, "TH")
    region = Region(frozenset((x, y) for x in range(3, 9) for y in range(5, 11)))
    lay = Layout(region, [th], th, {(3, 7): 1})
    view = layout_to_view(lay)
    assert view["origin"] == [3, 5]
    # base-map buildings stay relative (origin subtracted, times cell)
    assert view["buildings"][0]["x"] == 0
    assert view["buildings"][0]["y"] == 0
