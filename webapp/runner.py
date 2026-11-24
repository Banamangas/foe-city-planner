from __future__ import annotations

import queue
import threading
import time
import uuid

from foeopt.legality import check as check_legality
from foeopt.model import Layout
from foeopt.stats import city_stats
from foeopt.roads_first import RoadsFirstSearch
from webapp.collector import LayoutCollector, layout_to_dict


def _parse_range(spec: str):
    """"off" -> None; "3,4" -> (3, 4). The UI passes strings; the search wants a
    tuple or None so the feature stays off by default."""
    if not spec or spec == "off":
        return None
    lo, hi = spec.split(",")
    return (int(lo), int(hi))


def _parse_pitches(spec: str):
    """"off" -> None (the generator's built-in range); "12-18" -> (12,...,18)."""
    if not spec or spec == "off":
        return None
    lo, hi = spec.split("-")
    return tuple(range(int(lo), int(hi) + 1))


def _parse_modes(spec: str):
    """'off' means emit every mode, i.e. the historical generator behaviour."""
    if not spec or spec == "off":
        return None
    return (spec,)


class JobBusy(RuntimeError):
    """Another optimisation is still running (one active job at a time)."""

    def __init__(self, job_id: str):
        super().__init__(f"an optimisation is already running ({job_id}); stop it first")
        self.job_id = job_id


class JobManager:
    # Admission control: every run already uses workers x probe_workers solver
    # threads, so a second concurrent run would only halve both. One at a time.
    MAX_ACTIVE = 1

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, layout: Layout, *, time_box: float, patterns: int = 200,
               probe_limit: float = 60.0, workers: int = 4,
               probe_workers: int = 4, th_anchors: str = "full",
               k_start="auto", concurrent_levels: int = 1,
               seed_polish: int = 0, symmetry_breaking: bool = False,
               pattern_family: str = "comb", stub_priority: bool = False,
               lane_cap: int | None = None, warm_start: bool = False,
               warm_start_budget: float = 30.0,
               quality_index_band: str = "off", lane_pitches: str = "off",
               exact_repair: float = 0.0, comb_modes: str = "alternate",
               objective_limit: float = 0.0,
               objective_polish: float = 0.0,
               exact_finish: bool = False,
               polish_top: int = 3,
               polish_parallel: int = 0,
               polish_threads: int | None = None,
               exact_finish_workers: int = 0,
               probe_model: str = "position",
               military: str = "connect",
               off_road: frozenset[int] = frozenset(),
               rebase_s: float = 0.0,
               rebase_iterate: bool = False,
               road_witness: bool = False,
               fillers_in_model: bool = False,
               seed_input: bool = False,
               scheduler: str = "batch",
               early_publish: bool = False,
               closure: str = "bfs",
               union_polish: float = 0.0,
               union_m: int = 3,
               mutation_polish: bool = False,
               mutation_reserve: float = 0.0,
               mutation_starts: int = 1,
               mutation_reserve_min_box: float = 0.0,
               edit_info: dict | None = None) -> str:
        """Start a RoadsFirstSearch in a background thread and return its id.

        Keyword names match webapp.params.OPTION_SPECS one for one, so the
        Flask layer can splat parse_options() straight in here. `edit_info`
        (plan E: buildings to store, buildings added) rides along on every
        published layout and on the result; `layout` is then the EDITED city,
        which every result is legality-checked against. `off_road`: entity ids
        the player keeps off the road (not an option spec; /api/optimize
        builds it from `keep_unconnected`).
        """
        job_id = uuid.uuid4().hex
        stop_event = threading.Event()
        improvements: queue.Queue = queue.Queue()
        layouts: queue.Queue = queue.Queue()
        state = {"state": "running", "start": time.monotonic(), "end": None,
                 "result": None, "error": None,
                 "phase": None, "layouts_found": 0}
        with self._lock:
            active = [jid for jid, j in self._jobs.items()
                      if j["state"]["state"] == "running"]
            if len(active) >= self.MAX_ACTIVE:
                raise JobBusy(active[0])
            self._jobs[job_id] = {
                "state": state,
                "stop_event": stop_event,
                "improvements": improvements,
                "layouts": layouts,
            }

        last_legality: dict = {}
        collector = LayoutCollector(layout, military=military, off_road=off_road,
                                  extra=edit_info)

        def on_layout(lay, k, achieved):
            # Every validated layout the search finds, not only improvements;
            # each kept one is streamed as a "layout" event.
            entry = collector.offer(lay, k, achieved)
            state["layouts_found"] = collector.count
            if entry is not None:
                layouts.put(entry)

        def on_improvement(best_layout, k, achieved):
            # Every published layout carries its full game-legality verdict
            # (two-lane tiles, chain links, inventory...) and the policy used.
            leg = check_legality(best_layout, layout, military=military,
                                 off_road=off_road).as_dict()
            leg["military"] = military
            last_legality.clear()
            last_legality.update(leg)
            imp = {"k": k, "achieved": achieved, "legality": leg,
                   "stats": city_stats(best_layout, reference=layout),
                   **layout_to_dict(best_layout)}
            if edit_info:
                imp.update(edit_info)
            improvements.put(imp)

        def on_status(k, level_status, probes_done, probes_total):
            pass

        def on_phase(name):
            state["phase"] = name

        def should_stop():
            return stop_event.is_set()

        def worker():
            try:
                # The repack that produces the CP-SAT placement hints runs here,
                # not in the request thread, so /api/optimize returns immediately.
                # The warm start is charged AGAINST the user's time box, not
                # added on top of it. It used to run entirely outside the box --
                # a 60 s request with warm_start on took 90 s minimum. The user
                # asked for a total budget; every phase spends from it.
                hint_layout = None
                search_box = time_box
                if warm_start:
                    from foeopt.packer import repack
                    spent = min(warm_start_budget, max(1.0, time_box * 0.5))
                    t_ws = time.monotonic()
                    hint_layout = repack(layout, budget_seconds=spent).layout
                    search_box = max(1.0, time_box - (time.monotonic() - t_ws))
                search = RoadsFirstSearch(
                    layout, time_box=search_box, patterns=patterns,
                    probe_limit=probe_limit, workers=workers,
                    probe_workers=probe_workers, th_anchors=th_anchors,
                    k_start=k_start, concurrent_levels=concurrent_levels,
                    seed_polish=seed_polish, symmetry_breaking=symmetry_breaking,
                    pattern_family=pattern_family, stub_priority=stub_priority,
                    lane_cap=lane_cap, hint_layout=hint_layout,
                    quality_index_band=_parse_range(quality_index_band),
                    lane_pitches=_parse_pitches(lane_pitches),
                    exact_repair=exact_repair,
                    comb_modes=_parse_modes(comb_modes),
                    objective_limit=objective_limit,
                    objective_polish=objective_polish,
                    exact_finish=exact_finish,
                    polish_top=polish_top,
                    polish_parallel=polish_parallel,
                    polish_threads=polish_threads,
                    exact_finish_workers=exact_finish_workers,
                    probe_model=probe_model,
                    military=military,
                    off_road=off_road,
                    rebase_s=rebase_s,
                    rebase_iterate=rebase_iterate,
                    road_witness=road_witness,
                    fillers_in_model=fillers_in_model,
                    seed_input=seed_input,
                    scheduler=scheduler,
                    early_publish=early_publish and scheduler == "queue",
                    closure=closure,
                    union_polish=union_polish,
                    union_m=union_m,
                    mutation_polish=mutation_polish,
                    mutation_reserve=mutation_reserve,
                    mutation_starts=mutation_starts,
                    mutation_reserve_min_box=mutation_reserve_min_box,
                )
                res = search.run(on_improvement=on_improvement,
                                 on_status=on_status,
                                 should_stop=should_stop,
                                 on_phase=on_phase,
                                 on_layout=on_layout)
                res["layouts"] = collector.entries()
                if last_legality:
                    res["legality"] = dict(last_legality)
                if edit_info:
                    res["edits"] = edit_info
                self._finish(state, "done", result=res)
            except Exception as exc:
                self._finish(state, "error", error=f"{type(exc).__name__}: {exc}")

        threading.Thread(target=worker, daemon=True).start()
        return job_id

    def _finish(self, state: dict, final: str, result=None, error=None) -> None:
        """Publish the terminal state atomically: readers holding the lock see
        either 'running' or the complete (state, result, error, end) snapshot,
        never 'done' with a result still missing."""
        with self._lock:
            state.update(result=result, error=error, end=time.monotonic(), state=final)

    def snapshot(self, job_id: str) -> dict | None:
        """One coherent view of a job, or None if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            st = job["state"]
            end = st["end"] if st["end"] is not None else time.monotonic()
            return {"state": st["state"], "elapsed": round(end - st["start"], 1),
                    "error": st["error"], "result": st["result"],
                    "stopped": job["stop_event"].is_set(),
                    "phase": st["phase"], "layouts_found": st["layouts_found"]}

    def pop_improvement(self, job_id: str, timeout: float = 0.1) -> dict | None:
        return self._pop(job_id, "improvements", timeout)

    def pop_layout(self, job_id: str, timeout: float = 0.0) -> dict | None:
        """The next kept layout entry (see LayoutCollector), or None."""
        return self._pop(job_id, "layouts", timeout)

    def _pop(self, job_id: str, channel: str, timeout: float) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        try:
            if timeout <= 0:
                return job[channel].get_nowait()
            return job[channel].get(timeout=timeout)
        except queue.Empty:
            return None

    def status(self, job_id: str) -> dict:
        snap = self.snapshot(job_id)
        if snap is None:
            return {"state": "error", "elapsed": 0, "error": "unknown job"}
        return {k: snap[k] for k in ("state", "elapsed", "error", "phase",
                                    "layouts_found")}

    def result(self, job_id: str) -> dict | None:
        snap = self.snapshot(job_id)
        return None if snap is None else snap["result"]

    def is_done(self, job_id: str) -> bool:
        snap = self.snapshot(job_id)
        return snap is None or snap["state"] in ("done", "error")

    def exists(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._jobs

    def stop(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            job["stop_event"].set()

    def stop_all(self) -> None:
        """Ask every job that is not done to stop."""
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job["state"]["state"] not in ("done", "error"):
                job["stop_event"].set()

    def any_running(self) -> bool:
        with self._lock:
            return any(j["state"]["state"] == "running" for j in self._jobs.values())

    def elapsed(self, job_id: str) -> float:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return 0.0
        return time.monotonic() - job["state"]["start"]
