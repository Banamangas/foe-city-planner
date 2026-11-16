"""Backlog S2: objective polish with candidates solved concurrently (threads)."""
import threading
import time

import pytest

import foeopt.roads_first as rf
from tests.roads_first.test_objective import _corridor_layout

# Four 1x1 consumers on a 10-cell corridor road; every placement is feasible,
# the optimum is 3 needed cells (two consumers either side of x=2..3).
FAR = {10: (11, 1, 1, 1), 11: (10, 1, 1, 1), 12: (11, 3, 1, 1), 13: (10, 3, 1, 1)}
MID = {10: (7, 1, 1, 1), 11: (6, 1, 1, 1), 12: (7, 3, 1, 1), 13: (6, 3, 1, 1)}
NEAR = {10: (5, 1, 1, 1), 11: (4, 1, 1, 1), 12: (5, 3, 1, 1), 13: (4, 3, 1, 1)}


def _search(**kw):
    lay, pat = _corridor_layout()
    return rf.RoadsFirstSearch(lay, time_box=60, workers=2, probe_workers=2,
                               objective_polish=0.5, **kw), pat


def _run(search, cands, best, budget=20.0):
    seen = []
    info = search._apply_objective_polish(cands, best,
                                          lambda l, k, a: seen.append((k, a, dict(l.roads))),
                                          time.monotonic() + budget)
    return info, seen


def test_parallel_matches_sequential_when_every_solve_is_optimal():
    pytest.importorskip("ortools")
    seq, pat = _search()
    par, _ = _search(polish_parallel=3)
    cands = [(11, 10, pat, FAR), (9, 10, pat, MID), (7, 10, pat, NEAR)]
    si, ss = _run(seq, cands, 11)
    pi, ps = _run(par, cands, 11)
    assert si["after"] == pi["after"] <= 3
    assert all(r["status"] == "OPTIMAL" for r in si["per_skeleton"] + pi["per_skeleton"])
    assert si["tried"] == pi["tried"] == 3
    # same final layout; parallel publishes once (the best), never a worse one
    assert ps == [ss[-1]]
    assert pi["parallel"] == 3 and pi["threads_each"] == 1        # 2x2 threads // 3
    assert si["parallel"] == 1 and "wall_s" in si and "wall_s" in pi


def test_polish_threads_sets_the_split():
    _, pat = _search()
    par, _ = _search(polish_parallel=3, polish_threads=16)
    seen_threads = []

    def fake(cand, limit, threads):
        seen_threads.append(threads)
        return None, None, {"k": cand[1], "before": cand[0], "after": None,
                            "limit_s": limit, "solve_s": 0, "wall_s": 0,
                            "status": "UNKNOWN", "threads": threads}

    par._polish_one = fake
    info, _ = _run(par, [(11, 10, pat, FAR)] * 3, 11)
    assert seen_threads == [5, 5, 5] and info["threads_each"] == 5
    # fewer candidates than slots: the threads go to the ones that exist
    seen_threads.clear()
    info, _ = _run(par, [(11, 10, pat, FAR)] * 2, 11)
    assert seen_threads == [8, 8] and info["parallel"] == 2


def test_parallel_respects_the_deadline_and_splits_waves(monkeypatch):
    """top 4 on 2 slots = 2 waves: the first wave gets half the window, and
    the phase ends by the deadline even though every solve uses its full limit."""
    _, pat = _search()
    par, _ = _search(polish_parallel=2, polish_top=4)
    limits = []
    lock = threading.Lock()

    def slow(pattern, region, consumers, positions, *, limit, **kw):
        with lock:
            limits.append(limit)
        time.sleep(limit)                      # a solve that never proves early
        return None

    monkeypatch.setattr(rf, "minimize_needed", slow)
    budget = rf.OBJECTIVE_MARGIN_S + 2 * 2.5
    t0 = time.monotonic()
    info, seen = _run(par, [(11, 10, pat, FAR)] * 4, 11, budget=budget)
    wall = time.monotonic() - t0
    assert info["tried"] == 4 and seen == []
    assert wall <= budget                      # margin absorbs thread overhead
    first, second = sorted(limits[:2]), sorted(limits[2:])
    assert all(2.0 <= x <= 2.5 for x in first)            # (budget - margin) / 2
    assert all(x <= 2.5 + 0.2 for x in second)


def test_out_of_time_candidates_are_skipped_not_overrun(monkeypatch):
    _, pat = _search()
    par, _ = _search(polish_parallel=3)
    monkeypatch.setattr(rf, "minimize_needed",
                        lambda *a, **k: pytest.fail("must not start a solve"))
    info, seen = _run(par, [(11, 10, pat, FAR)] * 3, 11, budget=1.0)
    assert info["tried"] == 0 and info["after"] == 11 and seen == []


def test_ties_go_to_the_lowest_candidate_index_not_the_first_finisher():
    _, pat = _search()
    par, _ = _search(polish_parallel=3)

    def fake(cand, limit, threads):
        time.sleep({0: 0.3, 1: 0.0, 2: 0.15}[cand[1]])   # index 1 finishes first
        lay = type("L", (), {"roads": {(cand[1], 0): 1}})()
        return lay, 5, {"k": cand[1], "before": 11, "after": 5, "limit_s": limit,
                        "solve_s": 0, "wall_s": 0, "status": "OPTIMAL", "threads": threads}

    par._polish_one = fake
    info, seen = _run(par, [(11, i, pat, FAR) for i in range(3)], 11)
    assert info["after"] == 5 and seen == [(0, 5, {(0, 0): 1})]


def test_stop_request_skips_unstarted_candidates():
    _, pat = _search()
    par, _ = _search(polish_parallel=2, polish_top=4)
    calls = []

    def fake(cand, limit, threads):
        calls.append(cand[1])
        return None, None, {"k": cand[1], "before": 11, "after": None, "limit_s": limit,
                            "solve_s": 0, "wall_s": 0, "status": "UNKNOWN", "threads": threads}

    par._polish_one = fake
    info = par._apply_objective_polish([(11, i, pat, FAR) for i in range(4)], 11, None,
                                       time.monotonic() + 30, should_stop=lambda: True)
    assert calls == [] and info["tried"] == 0
