import random
import time
import pytest
from types import SimpleNamespace
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern
from foeopt import roads_first as mod


def test_probe_level_sequential_fallback_matches_today():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    call_order = []
    fake_layout = SimpleNamespace(roads=set(), buildings=[])

    def fake_run_probe(payload):
        pat, k, pat_index = payload
        call_order.append(pat.params)
        if len(call_order) == 1:
            return {"k": k, "params": pat.params, "status": "SAT",
                    "achieved": k, "secs": 0.1,
                    "layout": fake_layout, "pat_index": pat_index}
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.1, "layout": None,
                "pat_index": pat_index}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "_run_probe", fake_run_probe)

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    log_rows = []

    def log(row):
        log_rows.append(row)

    region_set = set(region.cells)
    rng = random.Random(0)
    try:
        status, best = mod._probe_level(lay, region_set, [c1], 1, rng,
                                        FakeArgs, log, pool=None)
    finally:
        monkeypatch.undo()

    pats = list(mod.generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    expected_order = [p.params for p in pats if mod.prefilter(p, region_set, [c1]) is None]
    assert call_order == expected_order
    assert status == "FEASIBLE"
    assert best == 1
    assert any(r.get("status") == "SAT" for r in log_rows)


def test_probe_level_defaults_to_comb_family(monkeypatch):
    """params without a pattern_family attribute (e.g. old callers/tests)
    must still dispatch to generate_patterns -- the comb family stays the
    default with zero behavior change."""
    calls = []
    real_comb = mod.generate_patterns
    def spy_comb(*a, **kw):
        calls.append("comb")
        return real_comb(*a, **kw)
    def spy_lane(*a, **kw):
        calls.append("lane")
        return []
    monkeypatch.setattr(mod, "generate_patterns", spy_comb)
    monkeypatch.setattr(mod, "generate_lane_patterns", spy_lane)

    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    mod._probe_level(lay, set(region.cells), [c1], 1, random.Random(0),
                     FakeArgs, lambda r: None, pool=None)
    assert calls == ["comb"]


def test_probe_level_pattern_family_lane_dispatches_to_lane_generator(monkeypatch):
    calls = []
    def spy_comb(*a, **kw):
        calls.append("comb")
        return []
    def spy_lane(*a, **kw):
        calls.append("lane")
        return []
    monkeypatch.setattr(mod, "generate_patterns", spy_comb)
    monkeypatch.setattr(mod, "generate_lane_patterns", spy_lane)

    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600
        pattern_family = "lane"

    mod._probe_level(lay, set(region.cells), [c1], 1, random.Random(0),
                     FakeArgs, lambda r: None, pool=None)
    assert calls == ["lane"]


def _batch_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    return Layout(region, [th, c1], th, {}), c1, region


class _FakeArgs:
    patterns = 5
    probe_limit = 30.0
    probe_workers = 1
    deadline = time.monotonic() + 600


def test_probe_levels_batch_rng_consumption_matches_sequential(monkeypatch):
    """Determinism invariant idea #7 depends on: generating patterns for a
    batch of k's must consume `rng` in the same order (same patterns) as
    calling _probe_level once per k, sequentially, from the same starting
    rng state -- exactly how RoadsFirstSearch.run() shares one rng object
    across level() calls."""
    lay, c1, region = _batch_layout()
    region_set = set(region.cells)

    def fake_run_probe_seq(payload):
        pat, k, *_rest = payload
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.0, "layout": None, "pos": None}
    monkeypatch.setattr(mod, "_run_probe_seq", fake_run_probe_seq)

    generated = {}
    real_gen = mod.generate_patterns
    def spy_gen(region_, w, l, k, rng, n, **kw):
        pats = list(real_gen(region_, w, l, k, rng, n, **kw))
        generated.setdefault(k, []).append([p.params for p in pats])
        return pats
    monkeypatch.setattr(mod, "generate_patterns", spy_gen)

    ks = [1, 2, 3]

    rng_batch = random.Random(0)
    mod._probe_levels_batch(lay, region_set, [c1], ks, rng_batch, _FakeArgs,
                            lambda r: None, pool=None)
    batch_result = {k: generated[k][-1] for k in ks}
    generated.clear()

    rng_seq = random.Random(0)
    for k in ks:
        mod._probe_level(lay, region_set, [c1], k, rng_seq, _FakeArgs,
                         lambda r: None, pool=None)
    seq_result = {k: generated[k][-1] for k in ks}

    assert batch_result == seq_result, (
        "batched pattern generation must consume rng in the same order as "
        "sequential per-k calls -- otherwise concurrent_levels changes the "
        "search, not just its speed")


def _fake_pattern(k, i):
    return Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2)}),
                   params={"k": k, "i": i})


def test_probe_levels_batch_pool_none_deadline_interrupts_correctly(monkeypatch):
    """pool=None, deadline trips while probing k=2's first pattern (which is
    SAT): k=1 (fully completed before the cutoff) gets the standard 3-way
    classification (INFEASIBLE, both its patterns cleanly UNSAT); k=2 (the
    interrupted level) gets the 2-way rule (FEASIBLE, since a SAT was found
    before the cutoff); k=3 (never started) is INCONCLUSIVE -- no evidence
    either way, must not be misreported as INFEASIBLE."""
    lay, c1, region = _batch_layout()
    region_set = set(region.cells)

    monkeypatch.setattr(mod, "prefilter", lambda pat, region, consumers: None)
    monkeypatch.setattr(mod, "generate_patterns",
                        lambda region, w, l, k, rng, n, **kw: [_fake_pattern(k, 0), _fake_pattern(k, 1)])

    clock = {"now": 0.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["now"])

    def fake_run_probe_seq(payload):
        pat, k, *_rest = payload
        if k == 2 and pat.params["i"] == 0:
            clock["now"] = 1000.0
            return {"k": k, "params": pat.params, "status": "SAT",
                    "achieved": 2, "secs": 0.1,
                    "layout": SimpleNamespace(roads=set(), buildings=[]), "pos": None}
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.1, "layout": None, "pos": None}
    monkeypatch.setattr(mod, "_run_probe_seq", fake_run_probe_seq)

    class Deadline:
        deadline = 500.0
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1

    improvements = []
    out = mod._probe_levels_batch(lay, region_set, [c1], [1, 2, 3], random.Random(0),
                                  Deadline, lambda r: None, pool=None,
                                  on_improvement=lambda vlay, k, achieved: improvements.append((k, achieved)))

    assert out[1] == ("INFEASIBLE", None)      # fully probed, all refuted
    assert out[2] == ("FEASIBLE", 2)
    # k=3 was never reached at all. Sharpened 2026-08-03 from INCONCLUSIVE
    # ("probed, undecided") to UNDERSAMPLED ("not finished") -- the two call for
    # opposite fixes: raise probe_limit vs raise time_box.
    assert out[3] == ("UNDERSAMPLED", None)
    assert improvements == [(2, 2)]


def test_probe_levels_batch_pool_none_interrupted_all_unsat_so_far_is_undersampled(monkeypatch):
    """The interrupted level never sees a SAT before the cutoff -- it must not
    be INFEASIBLE (we didn't prove anything).

    Since 2026-08-03 this is UNDERSAMPLED rather than INCONCLUSIVE, which is
    what this test always meant: "we didn't finish testing it".
    """
    lay, c1, region = _batch_layout()
    region_set = set(region.cells)

    monkeypatch.setattr(mod, "prefilter", lambda pat, region, consumers: None)
    monkeypatch.setattr(mod, "generate_patterns",
                        lambda region, w, l, k, rng, n, **kw: [_fake_pattern(k, 0), _fake_pattern(k, 1)])

    clock = {"now": 0.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["now"])

    def fake_run_probe_seq(payload):
        pat, k, *_rest = payload
        if k == 1 and pat.params["i"] == 0:
            clock["now"] = 1000.0
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.1, "layout": None, "pos": None}
    monkeypatch.setattr(mod, "_run_probe_seq", fake_run_probe_seq)

    class Deadline:
        deadline = 500.0
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1

    out = mod._probe_levels_batch(lay, region_set, [c1], [1, 2], random.Random(0),
                                  Deadline, lambda r: None, pool=None)
    assert out[1] == ("UNDERSAMPLED", None), (
        "an interrupted level with zero SAT so far must not be misreported "
        "as INFEASIBLE just because everything tested so far was clean")
    # k=2 was never reached either -- same reasoning.
    assert out[2] == ("UNDERSAMPLED", None)


def test_probe_levels_batch_pool_dispatches_one_imap_unordered_call_across_all_ks(monkeypatch):
    """The whole point of idea #7: patterns from multiple k's must share ONE
    pool.imap_unordered call (removing the per-level barrier), not one call
    per level."""
    lay, c1, region = _batch_layout()
    region_set = set(region.cells)

    monkeypatch.setattr(mod, "prefilter", lambda pat, region, consumers: None)
    monkeypatch.setattr(mod, "generate_patterns",
                        lambda region, w, l, k, rng, n, **kw: [_fake_pattern(k, 0), _fake_pattern(k, 1)])

    calls = []

    class FakePool:
        def imap_unordered(self, fn, payloads):
            payloads = list(payloads)
            calls.append(payloads)
            for pat, k, idx in payloads:
                yield {"k": k, "params": pat.params, "status": "UNSAT",
                      "achieved": None, "secs": 0.0, "layout": None,
                      "pat_index": idx, "pos": None}

        def terminate(self):
            pass

    out = mod._probe_levels_batch(lay, region_set, [c1], [1, 2, 3], random.Random(0),
                                  _FakeArgs, lambda r: None, pool=FakePool())
    assert len(calls) == 1, f"expected one merged imap_unordered call, got {len(calls)}"
    assert {p[1] for p in calls[0]} == {1, 2, 3}, "merged payload must span every k in the batch"
    assert all(status == "INFEASIBLE" for status, _ in out.values())


def test_probe_levels_batch_pool_deadline_does_not_refute_unprobed_levels(monkeypatch):
    """FIXED 2026-08-03. This test previously pinned the bug as a deliberate
    quirk: on a deadline the pooled branch terminates and falls through to the
    tail classifier, so a level that received ZERO results reported INFEASIBLE
    -- a refutation on no evidence.

    That is how the same k on FR17 came back FEASIBLE, INCONCLUSIVE or
    INFEASIBLE depending only on the order the walk reached it, and it produced
    two wrong conclusions in tasks/remaining-work.md. Such a level is now
    UNDERSAMPLED.

    Original description of the pooled branch, still accurate: unlike the
    pool=None branch, a deadline hit mid-stream does NOT
    special-case incomplete levels -- they fall through to the same 3-way
    tail logic as a fully-completed level. A level with zero results
    processed before the cutoff can therefore come out INFEASIBLE despite
    never being tested. This test documents that this is preserved exactly
    as `_probe_level` already behaved before idea #7 (not something this
    refactor introduces or fixes)."""
    lay, c1, region = _batch_layout()
    region_set = set(region.cells)

    monkeypatch.setattr(mod, "prefilter", lambda pat, region, consumers: None)
    monkeypatch.setattr(mod, "generate_patterns",
                        lambda region, w, l, k, rng, n, **kw: [_fake_pattern(k, 0)])

    clock = {"now": 0.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["now"])

    class FakePool:
        def __init__(self):
            self.terminated = False

        def imap_unordered(self, fn, payloads):
            for pat, k, idx in payloads:
                if k == 1:
                    clock["now"] = 1000.0
                yield {"k": k, "params": pat.params, "status": "UNSAT",
                      "achieved": None, "secs": 0.0, "layout": None,
                      "pat_index": idx, "pos": None}

        def terminate(self):
            self.terminated = True

    class Deadline:
        deadline = 500.0
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1

    pool = FakePool()
    out = mod._probe_levels_batch(lay, region_set, [c1], [1, 2], random.Random(0),
                                  Deadline, lambda r: None, pool=pool)
    assert pool.terminated
    # k=2 never got a single result (the deadline tripped while processing
    # k=1's only pattern). It must therefore claim nothing about feasibility.
    assert out[2] == ("UNDERSAMPLED", None)
