"""The `nonuniform` pattern family and its quality-index band filter.

This family holds the records on both measured cities (darkzig 94, FR16 76). It
differs from comb/lane in that its space (~10^19) cannot be enumerated, so it
SAMPLES -- these tests pin the invariants that matter: legality, the band
predicate, and that it is genuinely a different generator rather than a filter
over an existing one (the `max_lane_len` lesson).
"""
from __future__ import annotations

import random

from foeopt.roads_first import (QUALITY_INDEX_BAND, _check_pattern,
                                generate_lane_patterns, generate_nonuniform_patterns,
                                generate_patterns, quality_index)


def _region(side=24):
    return {(x, y) for x in range(side) for y in range(side)}


def test_patterns_are_legal_skeletons():
    reg = _region()
    for k in (25, 40, 60):
        pats = generate_nonuniform_patterns(reg, 2, 2, k, random.Random(0), 25,
                                            th_mode="full")
        assert pats, f"no patterns at k={k}"
        for p in pats:
            _check_pattern(p, reg, k)


def test_band_filter_admits_only_that_band():
    reg = _region()
    for band in ((3, 4), (2, 5)):
        pats = generate_nonuniform_patterns(reg, 2, 2, 40, random.Random(1), 30,
                                            th_mode="full", quality_index_band=band)
        assert pats
        for p in pats:
            qi = quality_index(reg, p.th, p.roads)
            assert band[0] <= qi <= band[1], f"{qi} outside {band}"


def test_band_filter_is_off_by_default():
    """Opt-in: without a band the generator must not silently filter."""
    reg = _region()
    pats = generate_nonuniform_patterns(reg, 2, 2, 40, random.Random(2), 40,
                                        th_mode="full")
    qs = {quality_index(reg, p.th, p.roads) for p in pats}
    assert len(qs) > 1, "unbanded generation should span several index values"


def test_quality_index_is_k_normalised_integer():
    """(2 - mfa) * k reduces to losses - 2c, so it must come out an integer and
    stay comparable across different k."""
    reg = _region()
    for k in (30, 50):
        for p in generate_nonuniform_patterns(reg, 2, 2, k, random.Random(3), 10,
                                              th_mode="full"):
            qi = quality_index(reg, p.th, p.roads)
            assert isinstance(qi, int)
            assert -4 * k <= qi <= 4 * k


def test_produces_topologies_the_other_families_cannot():
    """The max_lane_len lesson: a new 'family' that only reproduces existing
    patterns is a sampling filter, not a treatment."""
    reg = _region()
    k = 40
    known = {p.roads for p in generate_patterns(reg, 2, 2, k, random.Random(0),
                                                10 ** 9, th_mode="full")}
    known |= {p.roads for p in generate_lane_patterns(reg, 2, 2, k, random.Random(0),
                                                      10 ** 9, th_mode="full")}
    pats = generate_nonuniform_patterns(reg, 2, 2, k, random.Random(4), 60,
                                        th_mode="full")
    novel = [p for p in pats if p.roads not in known]
    assert len(novel) > len(pats) // 2, "generator largely reproduces comb/lane"


def test_empty_when_budget_impossible():
    reg = _region(8)
    assert generate_nonuniform_patterns(reg, 2, 2, 0, random.Random(0), 5) == []


def test_default_band_constant_matches_the_measured_records():
    assert QUALITY_INDEX_BAND == (3, 4)
