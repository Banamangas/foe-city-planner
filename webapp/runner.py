from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor

from foeopt.anneal import anneal
from foeopt.model import Layout
from foeopt.packer import PackResult, repack
from foeopt.report import road_estimate
from foeopt.router import route
from foeopt.validate import is_valid
from foeopt.viz import render_html


def _result(layout: Layout, packed) -> dict:
    lay = packed.layout
    placed_all = len(packed.unplaced) == 0
    return {
        "placed": len(lay.buildings),
        "unplaced": len(packed.unplaced),
        "roads": len(lay.roads),
        "estimate": road_estimate(layout),
        "valid": bool(placed_all and is_valid(lay)),
        "map_html": render_html(lay),
    }


def _anneal_base(layout: Layout, packed: PackResult, anneal_budget: float, seed: int):
    """Return a PackResult refined by annealing (or the base unchanged)."""
    if anneal_budget <= 0:
        return packed, len(packed.layout.roads)
    base_roads = len(packed.layout.roads)
    refined = anneal(packed.layout, budget_seconds=anneal_budget, seed=seed)
    final = Layout(layout.region, refined.layout.buildings,
                   refined.layout.townhall, route(refined.layout))
    return PackResult(final, packed.unplaced, packed.trials), base_roads


def run_repack(layout: Layout, *, budget: float, seed: int, anneal_budget: float = 0.0) -> dict:
    packed, base_roads = _anneal_base(layout, repack(layout, budget_seconds=budget, seed=seed),
                                      anneal_budget, seed)
    d = _result(layout, packed)
    d["base_roads"] = base_roads
    return d


def _sweep_one(args):
    layout, budget, seed = args
    r = repack(layout, budget_seconds=budget, seed=seed)
    return seed, len(r.layout.roads), len(r.unplaced), r


def run_sweep(layout: Layout, *, budget: float, seeds: int, workers: int,
              anneal_budget: float = 0.0) -> dict:
    tasks = [(layout, budget, s) for s in range(seeds)]
    results = []
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        for r in ex.map(_sweep_one, tasks):
            results.append(r)
    ok = [r for r in results if r[2] == 0]
    winner = min(ok, key=lambda r: r[1]) if ok else min(results, key=lambda r: (r[2], r[1]))
    packed, base_roads = _anneal_base(layout, winner[3], anneal_budget, 0)
    d = _result(layout, packed)
    d["base_roads"] = base_roads
    return d


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, fn) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {"state": "running", "start": time.monotonic(),
                                  "result": None, "error": None}

        def worker():
            try:
                res = fn()
                self._set(job_id, state="done", result=res)
            except Exception as exc:  # surfaced to the UI
                self._set(job_id, state="error", error=str(exc))

        threading.Thread(target=worker, daemon=True).start()
        return job_id

    def _set(self, job_id, **kw):
        with self._lock:
            self._jobs[job_id].update(kw)

    def status(self, job_id: str) -> dict:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return {"state": "error", "elapsed": 0, "error": "unknown job"}
            return {"state": j["state"], "elapsed": round(time.monotonic() - j["start"], 1),
                    "result": j["result"], "error": j["error"]}
