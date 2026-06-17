from foeopt.build import build_layout
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
