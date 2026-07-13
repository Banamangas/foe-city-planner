from __future__ import annotations

import queue
import threading
import time
import uuid

from foeopt.model import Layout
from foeopt.roads_first import RoadsFirstSearch


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
               k_start="auto") -> str:
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
                search = RoadsFirstSearch(
                    layout, time_box=time_box, patterns=patterns,
                    probe_limit=probe_limit, workers=workers,
                    probe_workers=probe_workers, th_anchors=th_anchors,
                    k_start=k_start,
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
