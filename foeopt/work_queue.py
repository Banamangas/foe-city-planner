"""Continuous work queue for the roads-first k-walk (scheduler="queue", backlog S1).

The batch scheduler (`_probe_levels_batch`) hands one level batch to a
`multiprocessing.Pool` and waits for ALL of it, then kills the pool with
`terminate()` when a slice expires. Measured on FR16/FR17 at a 120 s box,
workers sat idle 47-53% of the walk, and every terminate threw away the
in-flight probes and objectives and cost a pool rebuild (tasks/phase-b-baseline.md).

This module changes the scheduling only. The walk controller in
`RoadsFirstSearch.run` and every decision it makes are untouched: it still asks
for levels and gets one classification per level. What differs is when that
answer comes back and what happens to the work around it:

* **Persistent workers.** One set of processes for the whole walk; they are
  never terminated mid-run. The parent keeps at most `workers + workers // 2`
  tasks handed out, so a finishing worker always has the next task waiting.
* **One FIFO across levels.** Each request generates its levels (same rng, same
  prefilter, same round-robin order as the batch path) and appends their tasks
  to the queue. A level whose classification is final returns to the
  controller at once; a level is final when it is FEASIBLE (a validated SAT:
  later results can only lower its count), when all its tasks have come back,
  or when its deadline has passed. A FEASIBLE level's remaining tasks are NOT
  dropped -- the batch path would have run them before moving on, so they stay
  ahead of the next levels' tasks in the queue and their results (better counts,
  objective-polish candidates) are booked as they arrive. So the controller
  generates and enqueues the next levels while the workers are still busy.
* **Cooperative cancel instead of terminate.** Every task carries its level's
  effective deadline (min of walk deadline and slice), and the worker clamps
  each solve to it (`_TASK_CTX` in roads_first). A task that starts too late,
  or whose probe is cut short, comes back CANCELLED: not logged, not counted as
  probed, so the level classifies exactly as if it had been dropped
  (UNDERSAMPLED). Tasks still queued for an expired level are dropped in the
  parent. A user stop sets a shared Event; a watcher thread in each worker then
  calls `CpSolver.stop_search()` on the running solve. A stopped or clamped
  objective still returns its best placement, so partial SAT results reach
  the caller.
* At the end of the walk the controller drains the leftover tasks (bounded by
  their deadlines and by the live walk end, so the polish reserve is never
  borrowed), then closes the queue, which stops anything still running.
"""
from __future__ import annotations

import itertools
import multiprocessing
import queue as _queue
import threading
import time
import traceback
from collections import deque

from foeopt import roads_first as rf

SETTLE_GRACE_S = 1.0   # wait this long past a level's deadline for its in-flight tasks
WATCH_S = 0.05         # worker watcher period once a stop is requested
PUMP_S = 0.25          # longest the parent blocks on the result queue per pump
CLOSE_S = 5.0          # close(): time allowed for stopped workers to report and exit


# ------------------------------------------------------------------ worker side

def _watch(stop_event) -> None:
    """Stop every running solve as soon as the run is stopped, and keep doing
    so (a solve registered after the first sweep is caught by the next)."""
    stop_event.wait()
    while True:
        rf._stop_active_solvers()
        time.sleep(WATCH_S)


def _worker_main(task_q, result_q, stop_event, init_args, task_fn) -> None:
    rf._worker_init(*init_args)
    threading.Thread(target=_watch, args=(stop_event,), daemon=True).start()
    stopped = stop_event.is_set
    while True:
        item = task_q.get()
        if item is None:
            return
        tid, payload = item
        rf._TASK_CTX = {"deadline": payload[3], "stopped": stopped}
        try:
            result = task_fn(payload)
        except BaseException:  # noqa: BLE001 -- reported to, and raised by, the parent
            result_q.put(("error", tid, traceback.format_exc()))
            continue
        finally:
            rf._TASK_CTX = None
        result_q.put(("done", tid, result))


# ------------------------------------------------------------------ parent side

class _LevelRun:
    """One probing request for one k (a level re-probed after UNDERSAMPLED gets
    a new run with freshly generated patterns, exactly as in batch mode)."""
    __slots__ = ("k", "st", "deadline", "handler", "pending", "inflight", "settled")

    def __init__(self, k, st, deadline, handler):
        self.k, self.st, self.deadline, self.handler = k, st, deadline, handler
        self.pending = 0      # tasks still in the parent's queue
        self.inflight = 0     # tasks handed to a worker, result not back yet
        self.settled = False  # classification final and (to be) returned


class LevelQueue:
    """Persistent workers fed from one queue across k-levels.

    `levels(ks)` has the contract of `_probe_levels_batch`: it returns one
    `(status, best_achieved)` per k, books every result into the same
    bookkeeping (`_result_handler`), and fills `coverage`. Results that arrive
    after a level was returned (the rest of a FEASIBLE level) are booked too,
    and a change in that level's answer is reported via `on_level_update`.
    """

    def __init__(self, layout, region, consumers, rng, params, *, workers: int,
                 init_args: tuple, log=None, on_improvement=None, corpus=None,
                 scorer=None, score_threshold=None, filler_stats=None,
                 coverage=None, on_level_update=None, should_stop=None,
                 task_fn=None):
        self.layout, self.region, self.consumers = layout, region, consumers
        self.rng, self.params = rng, params
        self.log = log if log is not None else (lambda row: None)
        self.on_improvement = on_improvement
        self.corpus = corpus
        self.scorer, self.score_threshold = scorer, score_threshold
        self.filler_stats = filler_stats if filler_stats is not None else rf.new_filler_stats()
        self.coverage = coverage
        self.on_level_update = on_level_update
        self.should_stop = should_stop
        self.profile = getattr(params, "profile", None)
        self.workers = max(1, int(workers))
        self.cap = self.workers + max(1, self.workers // 2)
        self.task_q = multiprocessing.Queue()
        self.result_q = multiprocessing.Queue()
        self.stop_event = multiprocessing.Event()
        self.procs = [multiprocessing.Process(
            target=_worker_main,
            args=(self.task_q, self.result_q, self.stop_event, init_args,
                  task_fn if task_fn is not None else rf._run_probe),
            daemon=True) for _ in range(self.workers)]
        for p in self.procs:
            p.start()
        self.pending: deque[int] = deque()
        self.tasks: dict[int, tuple] = {}      # tid -> (run, pat, payload)
        self.outstanding = 0
        self.level_best: dict[int, int] = {}   # k -> best count over all runs
        self.reported: dict[int, tuple] = {}   # k -> answer last given for k
        self.latest_run: dict[int, _LevelRun] = {}
        self._tids = itertools.count()
        self.closed = False
        self.stats = {"tasks": 0, "dispatched": 0, "dropped": 0, "cancelled": 0,
                      "late_results": 0, "level_updates": 0}

    # ---------------------------------------------------------------- public

    def levels(self, ks) -> dict[int, tuple[str, int | None]]:
        return self.wait(self.submit(ks))

    def submit(self, ks) -> list[_LevelRun]:
        """Generate `ks` (in order, on the shared rng) and enqueue their tasks
        in the batch path's payload order, behind any work already queued."""
        params = self.params
        deadline = rf._effective_deadline(params)
        state = rf._generate_levels(self.layout, self.region, self.consumers, ks,
                                    self.rng, params, self.log, scorer=self.scorer,
                                    score_threshold=self.score_threshold)
        handler = rf._result_handler(state, params, self.log,
                                     on_improvement=self.on_improvement,
                                     corpus=self.corpus, filler_stats=self.filler_stats)
        runs = {k: _LevelRun(k, state[k], deadline, handler) for k in ks}
        self.latest_run.update(runs)
        by_level = [[(k, idx) for idx in range(len(state[k]["surviving"]))] for k in ks]
        if getattr(params, "interleave_levels", True):
            order = [p for row in itertools.zip_longest(*by_level) for p in row
                     if p is not None]
        else:
            order = [p for row in by_level for p in row]
        for k, idx in order:
            tid = next(self._tids)
            pat = state[k]["surviving"][idx]
            self.tasks[tid] = (runs[k], pat, (pat, k, idx, deadline))
            runs[k].pending += 1
            self.pending.append(tid)
        self.stats["tasks"] += len(order)
        for run in runs.values():
            self._maybe_settle(run)
        self._top_up()
        return list(runs.values())

    def wait(self, runs) -> dict[int, tuple[str, int | None]]:
        while True:
            open_runs = [r for r in runs if not r.settled]
            if not open_runs:
                break
            if self.should_stop is not None and self.should_stop():
                self.stop()
            now = time.monotonic()
            self._expire(now)
            for r in open_runs:
                if self.stop_event.is_set() or now >= r.deadline + SETTLE_GRACE_S:
                    self._settle(r)
            open_runs = [r for r in open_runs if not r.settled]
            if not open_runs:
                break
            nearest = min(r.deadline for r in open_runs) + SETTLE_GRACE_S
            self._pump(min(PUMP_S, max(0.01, nearest - now)))
        out = {}
        for r in runs:
            out[r.k] = self._answer(r)
            self.reported[r.k] = out[r.k]
        return out

    def drain(self, until: float) -> None:
        """Let the leftover tasks finish, but not past `until` (the live walk
        end) nor past a user stop."""
        while (self.outstanding or self.pending) and not self.closed:
            now = time.monotonic()
            if now >= until or (self.should_stop is not None and self.should_stop()):
                return
            self._expire(now)
            self._pump(min(PUMP_S, max(0.01, until - now)))

    def stop(self) -> None:
        """Cooperative stop: queued tasks are dropped, running solves stop."""
        self.stop_event.set()
        self._expire(time.monotonic())

    def close(self, abort: bool = False) -> None:
        """Stop everything still running, book what it reports (a stopped
        objective still returns a validated layout), and shut the workers down.
        `abort` (exception path) skips the booking."""
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        self.pending.clear()
        for _ in self.procs:
            self.task_q.put(None)
        t_end = time.monotonic() + CLOSE_S
        while self.outstanding and time.monotonic() < t_end:
            try:
                msg = self.result_q.get(timeout=0.1)
            except _queue.Empty:
                if not any(p.is_alive() for p in self.procs):
                    break
                continue
            if abort:
                if msg[0] == "done":
                    self.outstanding -= 1
                continue
            try:
                self._handle(msg)
            except RuntimeError:
                pass  # a worker error while shutting down changes nothing now
        for p in self.procs:
            p.join(timeout=max(0.0, t_end - time.monotonic()))
        for p in self.procs:
            if p.is_alive():   # end of run only: never while the walk uses them
                p.terminate()
                p.join()
        self.task_q.cancel_join_thread()
        self.result_q.cancel_join_thread()
        if self.profile is not None:
            self.profile.info["queue"] = dict(self.stats)

    # ---------------------------------------------------------------- internals

    def _answer(self, run) -> tuple[str, int | None]:
        best = self.level_best.get(run.k)
        if best is not None:
            return ("FEASIBLE", best)
        return rf.classify_level(run.st)

    def _settle(self, run) -> None:
        if run.settled:
            return
        run.settled = True
        if self.latest_run.get(run.k) is run:
            rf._fill_coverage({run.k: run.st}, [run.k], self.coverage)

    def _maybe_settle(self, run) -> None:
        if run.settled:
            return
        if (run.k in self.level_best
                or (run.pending == 0 and run.inflight == 0)):
            self._settle(run)

    def _expire(self, now: float) -> None:
        """Drop queued tasks whose level can no longer use them."""
        if not self.pending:
            return
        stopped = self.stop_event.is_set()
        keep: deque[int] = deque()
        touched = []
        for tid in self.pending:
            run = self.tasks[tid][0]
            if stopped or now >= run.deadline - rf.PROBE_MIN_S:
                del self.tasks[tid]
                run.pending -= 1
                self.stats["dropped"] += 1
                touched.append(run)
            else:
                keep.append(tid)
        self.pending = keep
        for run in touched:
            self._maybe_settle(run)

    def _top_up(self) -> None:
        while self.outstanding < self.cap and self.pending and not self.closed:
            tid = self.pending.popleft()
            run, pat, payload = self.tasks[tid]
            if (self.stop_event.is_set()
                    or time.monotonic() >= run.deadline - rf.PROBE_MIN_S):
                del self.tasks[tid]
                run.pending -= 1
                self.stats["dropped"] += 1
                self._maybe_settle(run)
                continue
            self.task_q.put((tid, payload))
            run.pending -= 1
            run.inflight += 1
            self.outstanding += 1
            self.stats["dispatched"] += 1

    def _pump(self, timeout: float) -> None:
        self._top_up()
        try:
            msg = self.result_q.get(timeout=timeout)
        except _queue.Empty:
            msg = None
            self._check_alive()
        while msg is not None:
            self._handle(msg)
            try:
                msg = self.result_q.get_nowait()
            except _queue.Empty:
                msg = None
        self._top_up()

    def _check_alive(self) -> None:
        dead = [p.exitcode for p in self.procs if p.exitcode is not None]
        if dead and not self.closed:
            raise RuntimeError(f"work-queue worker exited unexpectedly (exit codes {dead})")

    def _handle(self, msg) -> None:
        kind, tid, data = msg
        if kind == "error":
            raise RuntimeError(f"work-queue worker failed:\n{data}")
        run, pat, _ = self.tasks.pop(tid)
        self.outstanding -= 1
        run.inflight -= 1
        late = run.settled
        if data["status"] == "CANCELLED":
            self.stats["cancelled"] += 1
            if self.profile is not None:
                secs = (data.get("phases") or {}).get("task_total", 0.0)
                self.profile.add("task_total", secs)
                self.profile.add("task_cancelled", secs)
        else:
            run.handler(run.k, data, pat)
            if data["status"] == "SAT":
                self._note_best(run.k, data["achieved"])
        if late:
            self.stats["late_results"] += 1
            if self.latest_run.get(run.k) is run:
                rf._fill_coverage({run.k: run.st}, [run.k], self.coverage)
        else:
            self._maybe_settle(run)

    def _note_best(self, k: int, achieved: int) -> None:
        old = self.level_best.get(k)
        if old is not None and achieved >= old:
            return
        self.level_best[k] = achieved
        # A level already answered changed its answer (first SAT, or a lower
        # count): tell the controller's results table, as the batch path's
        # answer would have included it.
        if k in self.reported:
            answer = ("FEASIBLE", achieved)
            if self.reported[k] != answer:
                self.reported[k] = answer
                self.stats["level_updates"] += 1
                if self.on_level_update is not None:
                    self.on_level_update(k, answer)
        run = self.latest_run.get(k)
        if run is not None:
            self._maybe_settle(run)
