from __future__ import annotations

import queue
import threading
import time
import uuid

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


def layout_to_dict(layout: Layout) -> dict:
    """Serialize a validated Layout to the compact dict format for SSE/API."""
    return {
        "roads": [list(r) for r in sorted(layout.roads.keys())],
        "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                         b.footprint.width, b.footprint.length]
                      for b in layout.buildings},
    }


class JobManager:
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
               exact_repair: float = 0.0) -> str:
        """Start a RoadsFirstSearch in a background thread and return its id.

        Keyword names match webapp.params.OPTION_SPECS one for one, so the
        Flask layer can splat parse_options() straight in here.
        """
        job_id = uuid.uuid4().hex
        stop_event = threading.Event()
        improvements: queue.Queue = queue.Queue()
        state = {"state": "running", "start": time.monotonic(),
                 "result": None, "error": None}
        with self._lock:
            self._jobs[job_id] = {
                "state": state,
                "stop_event": stop_event,
                "improvements": improvements,
            }

        def on_improvement(best_layout, k, achieved):
            improvements.put({
                "k": k, "achieved": achieved,
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
                )
                res = search.run(on_improvement=on_improvement,
                                 on_status=on_status,
                                 should_stop=should_stop)
                state["state"] = "done"
                state["result"] = res
            except Exception as exc:
                state["state"] = "error"
                state["error"] = str(exc)

        threading.Thread(target=worker, daemon=True).start()
        return job_id

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
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {"state": "error", "elapsed": 0, "error": "unknown job"}
        return {"state": job["state"]["state"],
                "elapsed": round(time.monotonic() - job["state"]["start"], 1),
                "error": job["state"]["error"]}

    def result(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        return job["state"]["result"]

    def is_done(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return True
        return job["state"]["state"] in ("done", "error")

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
