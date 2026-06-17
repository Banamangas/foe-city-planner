from foeopt.build import build_layout
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.viz import render_html


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
