from __future__ import annotations

import os
import tempfile

from flask import Flask, jsonify, request, send_from_directory

from foeopt.editing import apply_edits
from foeopt.loader import load_layout
from foeopt.report import road_estimate
from webapp.runner import JobManager, run_repack, run_sweep

_STATIC = os.path.join(os.path.dirname(__file__), "static")


def create_app() -> Flask:
    app = Flask(__name__, static_folder=_STATIC, static_url_path="/static")
    state: dict = {"layout": None}
    jobs = JobManager()

    def _save_tmp(file_storage) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        file_storage.save(path)
        return path

    @app.get("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

    @app.post("/load")
    def load():
        if "city" not in request.files:
            return jsonify(error="no city file"), 400
        city_path = _save_tmp(request.files["city"])
        helper_path = _save_tmp(request.files["helper"]) if "helper" in request.files else None
        try:
            layout = load_layout(city_path, helper_path)
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400
        finally:
            for p in (city_path, helper_path):
                if p:
                    os.unlink(p)
        state["layout"] = layout
        buildings = [{
            "entity_id": b.entity_id, "name": b.name,
            "width": b.footprint.width, "length": b.footprint.length,
            "needs_road": b.needs_road, "is_townhall": b.is_townhall,
        } for b in layout.buildings]
        return jsonify(buildings=buildings, region_cells=len(layout.region.cells),
                       road_estimate=road_estimate(layout))

    @app.post("/run")
    def run():
        if state["layout"] is None:
            return jsonify(error="load a city first"), 400
        data = request.get_json(force=True, silent=True) or {}
        try:
            edited = apply_edits(state["layout"], set(data.get("remove_ids", [])),
                                 data.get("add_specs", []))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        mode = data.get("mode", "repack")
        budget = float(data.get("budget", 30))
        if mode == "sweep":
            seeds = int(data.get("seeds", 8))
            workers = int(data.get("workers", os.cpu_count() or 1))
            job_id = jobs.submit(lambda: run_sweep(edited, budget=budget, seeds=seeds, workers=workers))
        else:
            seed = int(data.get("seed", 0))
            job_id = jobs.submit(lambda: run_repack(edited, budget=budget, seed=seed))
        return jsonify(job_id=job_id)

    @app.get("/status/<job_id>")
    def status(job_id):
        return jsonify(jobs.status(job_id))

    return app


if __name__ == "__main__":
    create_app().run(port=5000, debug=False)
