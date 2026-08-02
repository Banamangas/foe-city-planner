"""A level must not claim a refutation it did not earn.

Before 2026-08-03, `classify` returned INFEASIBLE whenever no layout was found
and no probe had come back undecided -- without ever checking whether the
level's sample had actually been probed. On a deadline the pooled branch
terminates and classifies EVERY level, so levels with zero probes reported
INFEASIBLE on no evidence at all.

That is not a cosmetic mislabel. It made the same k on FR17 report FEASIBLE,
INCONCLUSIVE or INFEASIBLE depending only on the order the walk reached it, and
it is the root cause of two wrong conclusions recorded in
tasks/remaining-work.md (sections 3.2 and 4).
"""
import pytest

from foeopt.roads_first import LEVEL_STATUSES, _fill_coverage, classify_level


def _state(generated, surviving, probed, saw_nonproof=False, best=None):
    return {"pats": list(range(generated)),
            "surviving": list(range(surviving)),
            "order": probed,
            "saw_nonproof_failure": saw_nonproof,
            "best_achieved": best}


classify = classify_level


def test_zero_probes_is_never_a_refutation():
    """The exact bug: a level the deadline never reached used to say INFEASIBLE."""
    assert classify(_state(200, 200, probed=0))[0] == "UNDERSAMPLED"


def test_partially_probed_is_never_a_refutation():
    assert classify(_state(200, 200, probed=3))[0] == "UNDERSAMPLED"
    assert classify(_state(200, 200, probed=199))[0] == "UNDERSAMPLED"


def test_fully_probed_and_all_refuted_is_still_infeasible():
    """The honest case must survive: exhaustive over the sample."""
    assert classify(_state(200, 200, probed=200))[0] == "INFEASIBLE"


def test_fully_probed_with_an_undecided_probe_is_inconclusive():
    """Distinct from UNDERSAMPLED: here the sample WAS finished, but the solver
    ran out of time on individual patterns -- raise probe_limit, not time_box."""
    assert classify(_state(200, 200, probed=200, saw_nonproof=True))[0] == "INCONCLUSIVE"


def test_a_found_layout_always_wins():
    assert classify(_state(200, 200, probed=1, best=76)) == ("FEASIBLE", 76)


def test_everything_prefiltered_away_is_exhaustive_not_undersampled():
    """prefilter is sound -- it only rejects patterns that provably cannot work
    -- so a sample entirely rejected by it IS an exhaustive negative."""
    assert classify(_state(200, 0, probed=0))[0] == "INFEASIBLE"


def test_nothing_generated_says_nothing():
    assert classify(_state(0, 0, probed=0))[0] == "INCONCLUSIVE"


def test_status_vocabulary_is_declared():
    assert set(LEVEL_STATUSES) == {"FEASIBLE", "INFEASIBLE", "INCONCLUSIVE",
                                   "UNDERSAMPLED"}


def test_coverage_reports_how_much_of_the_sample_was_probed():
    """Without the numbers a caller still cannot tell 3-of-200 from 200-of-200."""
    state = {7: _state(200, 150, probed=3)}
    cov = {}
    _fill_coverage(state, [7], cov)
    assert cov[7] == {"generated": 200, "surviving": 150, "probed": 3}


def test_coverage_never_reports_more_probed_than_the_sample_holds():
    state = {7: _state(10, 4, probed=99)}
    cov = {}
    _fill_coverage(state, [7], cov)
    assert cov[7]["probed"] == 4


def test_coverage_is_optional_and_never_raises():
    _fill_coverage({1: _state(1, 1, 1)}, [1], None)
    _fill_coverage({}, [1, 2], {})          # missing levels are skipped


def test_both_probe_paths_report_coverage_and_filler_stats():
    """`run()` probes levels through TWO helpers -- `_probe_level` for a single
    k and `_probe_levels_batch` for a concurrent batch. Both must forward the
    coverage and filler tallies, or a level's numbers silently vanish depending
    on which path happened to reach it.

    Found by inspection after FR17 reported `probed ?/?` for its FIRST level --
    the one that gets the whole budget and matters most. The same omission was
    also dropping filler failures from that path.
    """
    import inspect
    import foeopt.roads_first as rf

    src = inspect.getsource(rf.RoadsFirstSearch.run)
    single = src[src.index("def level(k):"):src.index("def levels(ks):")]
    batch = src[src.index("def levels(ks):"):]
    for name, block in (("_probe_level", single), ("_probe_levels_batch", batch)):
        assert "coverage=level_coverage" in block, f"{name} drops coverage"
        assert "filler_stats=filler_stats" in block, f"{name} drops filler stats"
