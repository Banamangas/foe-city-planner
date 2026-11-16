from __future__ import annotations

import queue
import threading
import time
import uuid

from foeopt.legality import check as check_legality
from foeopt.model import Layout
from foeopt.roads_first import RoadsFirstSearch


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


def layout_to_dict(layout: Layout) -> dict:
    """Serialize a validated Layout to the compact dict format for SSE/API."""
    return {
        # [x, y, level]: level 2 marks a two-lane tile cell (older readers
        # that destructure [x, y] keep working).
        "roads": [[x, y, lvl] for (x, y), lvl in sorted(layout.roads.items())],
        "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                         b.footprint.width, b.footprint.length]
                      for b in layout.buildings},
    }


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
               probe_model: str = "position",
               military: str = "connect",
               rebase_s: float = 0.0,
               road_witness: bool = False,
               fillers_in_model: bool = False,
               seed_input: bool = False,
               scheduler: str = "batch") -> str:
        """Start a RoadsFirstSearch in a background thread and return its id.

        Keyword names match webapp.params.OPTION_SPECS one for one, so the
        Flask layer can splat parse_options() straight in here.
        """
        job_id = uuid.uuid4().hex
        stop_event = threading.Event()
        improvements: queue.Queue = queue.Queue()
        state = {"state": "running", "start": time.monotonic(), "end": None,
                 "result": None, "error": None}
        with self._lock:
            active = [jid for jid, j in self._jobs.items()
                      if j["state"]["state"] == "running"]
            if len(active) >= self.MAX_ACTIVE:
                raise JobBusy(active[0])
            self._jobs[job_id] = {
                "state": state,
                "stop_event": stop_event,
                "improvements": improvements,
            }

        last_legality: dict = {}

        def on_improvement(best_layout, k, achieved):
            # Every published layout carries its full game-legality verdict
            # (two-lane tiles, chain links, inventory...) and the policy used.
            leg = check_legality(best_layout, layout, military=military).as_dict()
            leg["military"] = military
            last_legality.clear()
            last_legality.update(leg)
            improvements.put({
                "k": k, "achieved": achieved, "legality": leg,
                **layout_to_dict(best_layout),
            })

        def on_status(k, level_status, probes_done, probes_total):
            pass

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
                    probe_model=probe_model,
                    military=military,
                    rebase_s=rebase_s,
                    road_witness=road_witness,
                    fillers_in_model=fillers_in_model,
                    seed_input=seed_input,
                    scheduler=scheduler,
                )
                res = search.run(on_improvement=on_improvement,
                                 on_status=on_status,
                                 should_stop=should_stop)
                if last_legality:
                    res["legality"] = dict(last_legality)
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
                    "stopped": job["stop_event"].is_set()}

    def pop_improvement(self, job_id: str, timeout: float = 0.1) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        try:
            return job["improvements"].get(timeout=timeout)
        except queue.Empty:
            return None

    def status(self, job_id: str) -> dict:
        snap = self.snapshot(job_id)
        if snap is None:
            return {"state": "error", "elapsed": 0, "error": "unknown job"}
        return {k: snap[k] for k in ("state", "elapsed", "error")}

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

    def elapsed(self, job_id: str) -> float:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return 0.0
        return time.monotonic() - job["state"]["start"]
