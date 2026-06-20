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
