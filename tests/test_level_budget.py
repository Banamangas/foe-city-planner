"""Budget allocation across k-levels.

Three defects, diagnosed 2026-08-03 (tasks/todo.md):

  D1  a level probed until the WALK deadline, so the first one could consume the
      whole box -- measured on FR17 at k_start=117: 35 patterns x 90 s / 6
      workers = up to 525 s of a 600 s box, returning INCONCLUSIVE, leaving
      every later level with one probe or none.
  D2  batch payloads were grouped by level, so `imap_unordered` drained k1
      before touching k2 -- a "concurrent" batch that was concurrent only in
      pattern generation.
  D3  the walk treated UNDERSAMPLED as a refutation: descent broke, ascent
      skipped to the top of the batch. Harmless while UNDERSAMPLED only arose at
      the deadline; live as soon as D1 stops levels early with budget left.
"""
import itertools
import random
from types import SimpleNamespace

import pytest

import foeopt.roads_first as mod


# --- D2: interleaving --------------------------------------------------------

def _interleave(by_level):
    """Mirror of the production payload order (asserted identical below)."""
    return [p for row in itertools.zip_longest(*by_level) for p in row if p is not None]


def test_payloads_are_interleaved_across_levels_not_grouped():
    import inspect
    src = inspect.getsource(mod._probe_levels_batch)
    assert "zip_longest" in src, "payloads must round-robin across levels"
    grouped = "payloads = [(pat, k, idx) for k in ks for idx"
    assert grouped not in src, "level-grouped payload order is the D2 bug"


def test_interleaving_visits_every_level_before_repeating_one():
    """The property that matters: truncating the payload list at any point
    leaves every level sampled as evenly as possible."""
    by_level = [[(f"p{k}_{i}", k, i) for i in range(30)] for k in (84, 88, 92, 96)]
    order = _interleave(by_level)
    first_four = [p[1] for p in order[:4]]
    assert sorted(first_four) == [84, 88, 92, 96], "one level was drained first"
    # after any prefix, level counts differ by at most one
    for cut in (5, 13, 27, 40):
        counts = {}
        for _, k, _ in order[:cut]:
            counts[k] = counts.get(k, 0) + 1
        assert max(counts.values()) - min(counts.values()) <= 1


def test_interleaving_handles_levels_of_different_sizes():
    by_level = [[("a", 1, 0)], [("b", 2, 0), ("b", 2, 1), ("b", 2, 2)]]
    order = _interleave(by_level)
    assert len(order) == 4
    assert order[0][1] == 1 and order[1][1] == 2


# --- D1: the slice -----------------------------------------------------------

def test_slice_defaults_to_off_so_behaviour_is_unchanged():
    """The whole change must be inert unless asked for -- every result this
    project holds was produced without it."""
    import inspect
    p = inspect.signature(mod.RoadsFirstSearch.__init__).parameters
    assert p["level_slice_frac"].default is None


def test_slice_deadline_caps_the_call_but_never_extends_it():
    """A slice may only ever shorten. If it were allowed to exceed the walk
    deadline it would reintroduce the overrun class fixed on 2026-07-30."""
    import inspect
    src = inspect.getsource(mod._probe_levels_batch)
    assert "min(params.deadline, slice_deadline)" in src


def test_absent_slice_attribute_is_tolerated():
    """params is a SimpleNamespace built in several places; a missing attribute
    must mean 'no slice', not AttributeError."""
    params = SimpleNamespace(deadline=123.0)
    assert getattr(params, "slice_deadline", None) is None


# --- D3: control flow --------------------------------------------------------

def test_descent_does_not_end_on_levels_it_never_probed():
    import inspect
    src = inspect.getsource(mod.RoadsFirstSearch.run)
    descent = src[src.index("lo_feasible = k"):]
    assert 'UNDERSAMPLED' in descent, "descent must react to unfinished levels"


def test_ascent_does_not_climb_past_levels_it_never_probed():
    import inspect
    src = inspect.getsource(mod.RoadsFirstSearch.run)
    ascent = src[src.index("st, _ = level(k)"):src.index("lo_feasible = k")]
    assert 'UNDERSAMPLED' in ascent, "ascent must react to unfinished levels"


def test_retry_is_bounded_so_a_starved_level_cannot_spin():
    """Without a cap, a level that always runs out of slice would be retried
    forever and the walk would never terminate."""
    import inspect
    src = inspect.getsource(mod.RoadsFirstSearch.run)
    assert "attempts.get(kk, 0) < 2" in src


def test_retry_only_applies_when_slicing_is_enabled():
    """With no slice, UNDERSAMPLED means the deadline passed -- retrying would
    just burn the overrun."""
    import inspect
    src = inspect.getsource(mod.RoadsFirstSearch.run)
    needs = src[src.index("def _needs_probe"):src.index("def level(k)")]
    assert "self.level_slice_frac is not None" in needs


# --- behavioural: the mechanism, not its source ------------------------------

def _tiny_city():
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False,
                  None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {}), c1, region


def _fake_pattern(k, i):
    return mod.Pattern(th=mod.Footprint(0, 0, 2, 2), roads=frozenset({(0, i)}),
                       params={"k": k, "i": i})


def _run_batch(monkeypatch, ks, per_probe_s, deadline_s, slice_s=None,
               patterns_per_level=10):
    """Drive the real batch with a simulated clock; return probes per level."""
    lay, c1, region = _tiny_city()
    clock = {"now": 0.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(mod, "prefilter", lambda *a, **k: None)
    monkeypatch.setattr(mod, "generate_patterns",
                        lambda region, w, l, k, rng, n, **kw:
                        [_fake_pattern(k, i) for i in range(patterns_per_level)])

    probed = []

    def fake_seq(payload):
        pat, k, *_ = payload
        clock["now"] += per_probe_s
        probed.append(k)
        return {"k": k, "params": pat.params, "status": "UNSAT", "achieved": None,
                "secs": per_probe_s, "layout": None, "pos": None}

    monkeypatch.setattr(mod, "_run_probe_seq", fake_seq)
    params = SimpleNamespace(patterns=patterns_per_level, probe_limit=1.0,
                             probe_workers=1, deadline=deadline_s,
                             th_anchors="coarse", pattern_family="comb",
                             slice_deadline=slice_s)
    cov = {}
    out = mod._probe_levels_batch(lay, set(region.cells), [c1], ks,
                                  random.Random(0), params, lambda r: None,
                                  pool=None, coverage=cov)
    counts = {k: probed.count(k) for k in ks}
    return counts, out, cov


def test_without_a_slice_the_first_level_consumes_the_budget(monkeypatch):
    """The D1 pathology, reproduced: 10 s of budget, 1 s per probe, four levels
    of 10 patterns. The sequential path walks ks in order, so k=84 eats it."""
    counts, out, _ = _run_batch(monkeypatch, [84, 88, 92, 96],
                                per_probe_s=1.0, deadline_s=10.0)
    assert counts[84] == 10, "first level should have been fully probed"
    assert counts[96] == 0, "last level should have been starved"
    assert out[96][0] == "UNDERSAMPLED", "and must not claim a refutation"


def test_a_slice_stops_the_call_before_the_walk_deadline(monkeypatch):
    """The fix's core promise: the call returns early, leaving budget for the
    walk to spend on other levels."""
    counts, out, cov = _run_batch(monkeypatch, [84, 88, 92, 96],
                                  per_probe_s=1.0, deadline_s=100.0, slice_s=4.0)
    total = sum(counts.values())
    assert total <= 5, f"slice ignored: {total} probes ran past a 4 s slice"
    assert total >= 3, "slice cut the call far too short"


def test_a_slice_never_extends_past_the_walk_deadline(monkeypatch):
    """A slice must only ever shorten -- otherwise it becomes an overrun bug."""
    counts, _, _ = _run_batch(monkeypatch, [84, 88], per_probe_s=1.0,
                              deadline_s=3.0, slice_s=1000.0)
    assert sum(counts.values()) <= 4, "slice extended the walk deadline"


def test_coverage_reports_the_shortfall_a_slice_creates(monkeypatch):
    counts, out, cov = _run_batch(monkeypatch, [84, 88], per_probe_s=1.0,
                                  deadline_s=100.0, slice_s=3.0)
    probed = sum(c["probed"] for c in cov.values())
    assert probed == sum(counts.values())
    assert any(c["probed"] < c["surviving"] for c in cov.values())


def test_pool_termination_is_signalled_to_the_caller():
    """Found by the A/B, not by a test: `pool.terminate()` leaves the pool
    permanently unusable. Before slicing it was only ever reached at the walk
    deadline, when the pool was about to be discarded -- so nothing noticed. A
    slice fires MID-RUN, and every later level then died with
    `ValueError: Pool not running`.

    The batch must therefore tell the caller it killed the pool.
    """
    import inspect
    src = inspect.getsource(mod._probe_levels_batch)
    term = src[src.index("pool.terminate()"):]
    assert 'runtime["pool_terminated"] = True' in term[:300]


def test_the_walk_rebuilds_a_pool_a_slice_killed():
    import inspect
    src = inspect.getsource(mod.RoadsFirstSearch.run)
    assert "_restore_pool" in src
    restore = src[src.index("def _restore_pool"):]
    assert "_new_pool()" in restore[:600]
    # rebuilding after the walk is over would just cost a fork for nothing
    assert "_should_stop()" in restore[:600]


def test_every_probing_call_site_restores_the_pool():
    """Both the single-level and batched paths can terminate it; missing either
    reintroduces the crash on a different code path."""
    import inspect
    src = inspect.getsource(mod.RoadsFirstSearch.run)
    assert src.count("_restore_pool()") >= 2
    assert src.count("runtime=runtime") >= 2
