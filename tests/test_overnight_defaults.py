"""Defaults changed on 2026-08-01 from the overnight matrix.

Each assertion here is a measurement, not a preference; the docstrings carry the
number so a future change has to argue with the evidence rather than the value.
Full data: tasks/remaining-work.md section 9.
"""
from foeopt.bounds import K_START_MARGIN, pick_k_start
from foeopt.loader import load_layout
from webapp.params import DEFAULTS


def test_nonuniform_k_start_margin_is_zero_not_minus_four():
    """At equal 600 s boxes: margin -4 gave FR16 76 and FR17 NOTHING; margin +0
    gave FR16 77 and FR17 115. -4 buys one road on one city and costs the other
    every result it has."""
    assert K_START_MARGIN["nonuniform"] == 0


def test_fr17_now_starts_where_results_actually_live():
    """FR17's productive start is 121. The old margin put it at 117, from which
    the walk spent its whole box ascending and returned FAMILY_TOO_WEAK."""
    lay = load_layout('CityMap-Born-FR17-2026-07-07.json')
    assert pick_k_start(lay, "nonuniform") == 121


def test_fr16_start_moves_by_exactly_the_margin_change():
    """FR16 was optimal at 84 and is now 88, costing a measured one road (76 ->
    77). That is the price of FR17 working at all -- recorded so it is not
    mistaken for a free change."""
    lay = load_layout('CityMap-Born-FR16-2026-07-07.json')
    assert pick_k_start(lay, "nonuniform") == 88


def test_quality_band_is_on_by_default():
    """Worth nothing on darkzig (101 with and without) and the difference
    between NOTHING and the all-time record on FR16 (76)."""
    assert DEFAULTS["quality_index_band"] == "3,4"


def test_comb_and_lane_margins_are_untouched():
    """Only nonuniform was measured this way; changing the others would be
    guessing."""
    assert K_START_MARGIN["comb"] == 8
    assert K_START_MARGIN["lane"] == 8
