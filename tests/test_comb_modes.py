"""The comb family's branch-mode lever.

`generate_patterns` hardcoded `for mode in ("both", "alternate")`, so the
pooled-log finding that `alternate` holds 9/9 SATs while `both` is 0/528 could
not be acted on at all. These tests pin the lever and, more importantly, pin
that leaving it unset changes nothing -- every prior result was produced with
both modes emitted, and must stay reproducible.
"""
import inspect
import random

import pytest

from foeopt.loader import load_layout
from foeopt.roads_first import COMB_MODES, RoadsFirstSearch, generate_patterns


@pytest.fixture(scope="module")
def city():
    lay = load_layout('CityMap-Born-FR16-2026-07-07.json')
    return set(lay.region.cells), lay.townhall.footprint


def gen(city, modes, k=96, n=500):
    region, th = city
    return generate_patterns(region, th.width, th.length, k,
                             random.Random(0), n, modes=modes)


def test_unset_is_byte_identical_to_the_old_hardcoded_behaviour(city):
    """The regression that matters: every past record was generated without
    this parameter, so the default must reproduce those pattern streams."""
    assert [p.roads for p in gen(city, None)] == [p.roads for p in gen(city, COMB_MODES)]


def test_selecting_alternate_emits_only_alternate(city):
    pats = gen(city, ("alternate",))
    assert pats
    assert {p.params["mode"] for p in pats} == {"alternate"}


def test_selecting_both_emits_only_both(city):
    pats = gen(city, ("both",))
    assert pats
    assert {p.params["mode"] for p in pats} == {"both"}


def test_default_emits_both_modes(city):
    assert {p.params["mode"] for p in gen(city, None)} == {"both", "alternate"}


def test_unknown_mode_is_rejected_loudly(city):
    region, th = city
    with pytest.raises(ValueError, match="unknown comb mode"):
        generate_patterns(region, th.width, th.length, 96, random.Random(0), 10,
                          modes=("diagonal",))


def test_search_exposes_the_lever_and_defaults_to_off():
    params = inspect.signature(RoadsFirstSearch.__init__).parameters
    assert "comb_modes" in params
    assert params["comb_modes"].default is None


# --- the shipped defaults ----------------------------------------------------

def test_product_default_is_alternate_but_the_generator_default_is_not():
    """The split matters. The PRODUCT ships `alternate` because it measured
    better (FR16 90 -> 82, FR17 nothing -> 124), but `generate_patterns` still
    emits both modes when unasked, so every record produced before 2026-08-01
    stays reproducible by calling the generator the way those runs called it."""
    from webapp.params import BEST_PRESET, DEFAULTS

    assert DEFAULTS["comb_modes"] == "alternate"
    assert BEST_PRESET["comb_modes"] == "alternate"
    assert inspect.signature(generate_patterns).parameters["modes"].default is None


def test_off_restores_the_historical_behaviour():
    from webapp.runner import _parse_modes
    assert _parse_modes("off") is None          # -> generator emits both
    assert _parse_modes("alternate") == ("alternate",)
    assert _parse_modes("both") == ("both",)
