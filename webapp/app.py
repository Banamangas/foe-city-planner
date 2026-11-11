from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid

from flask import Flask, Response, jsonify, request, send_from_directory

from foeopt.loader import load_layout_from_dict, load_layout
from foeopt.report import road_estimate
from foeopt.viz import layout_to_view
from webapp.cache import CityCache
from foeopt.bounds import screen_city
from webapp.params import (
    BEST_PRESET, GROUP_LABELS, OPTION_SPECS, SMOKE_PRESET, OptionError, parse_options,
)
from webapp.runner import JobBusy, JobManager

_DIST = os.path.join(os.path.dirname(__file__), "dist")


def _city_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def _buildings_summary(layout) -> list[dict]:
    return [{
        "entity_id": b.entity_id, "name": b.name,
        "width": b.footprint.width, "length": b.footprint.length,
        "needs_road": b.needs_road, "is_townhall": b.is_townhall,
    } for b in layout.buildings]


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=_DIST, static_url_path="/assets_root")
    cache = CityCache(db_path or os.path.join(os.path.dirname(__file__), "cities.db"))
    jobs = JobManager()

    def _save_tmp(file_storage) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        file_storage.save(path)
        return path

    def _parse_and_cache(data, helper_data: dict | None = None) -> dict:
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        if helper_data is not None and "entities" in data:
            # Split export: keep the helper's catalog INSIDE the cached payload
            # so later loads (optimize, export, re-import) still resolve sizes,
            # road levels and chains. Only CityEntities is needed.
            data = {**data, "helper_data": {"CityEntities": helper_data.get("CityEntities", {})}}
        layout = load_layout_from_dict(data)
        payload = json.dumps(data).encode()
        city_id = _city_hash(payload)
        buildings = _buildings_summary(layout)
        cache.store_city(city_id, payload, buildings,
                         len(layout.region.cells), road_estimate(layout))
        return {
            "city_id": city_id,
            "buildings": buildings,
            "region_cells": len(layout.region.cells),
            "road_estimate": road_estimate(layout),
            # Microsecond instance screen (foeopt.bounds.screen_city): tells the
            # user up front whether this city is one the optimiser can help with,
            # instead of returning an empty result after a full time box. FR24
            # consumed 13 core-hours across 1182 probes before this existed.
            # Advisory only -- the UI must never use it to block a run.
            "screen": screen_city(layout),
            "map_view": layout_to_view(layout),
        }

    @app.get("/")
    def index():
        if not os.path.exists(os.path.join(_DIST, "index.html")):
            return jsonify(error="frontend not built; run `npm run build` in frontend/"), 503
        return send_from_directory(_DIST, "index.html")

    @app.post("/api/load")
    def api_load():
        data = request.get_json(silent=True)
        if data is None:
            return jsonify(error="invalid JSON body"), 400
        try:
            return jsonify(_parse_and_cache(data))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.post("/api/load/raw")
    def api_load_raw():
        if "city" not in request.files:
            return jsonify(error="no city file"), 400
        city_path = _save_tmp(request.files["city"])
        helper_path = _save_tmp(request.files["helper"]) if "helper" in request.files else None
        try:
            from foeopt.loader import read_json
            data = read_json(city_path)
            helper_data = read_json(helper_path) if helper_path else None
        except Exception as exc:
            return jsonify(error=f"could not read file: {exc}"), 400
        finally:
            for p in (city_path, helper_path):
                if p:
                    os.unlink(p)
        try:
            return jsonify(_parse_and_cache(data, helper_data))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.get("/api/options")
    def api_options():
        """Serve the run-parameter spec the Optimize panel renders itself from.

        webapp/params.py is the single source of truth: every knob, its type,
        range, default, help text and the CLI flag it mirrors.
        """
        return jsonify(options=OPTION_SPECS, groups=GROUP_LABELS,
                       presets={"smoke": SMOKE_PRESET, "best": BEST_PRESET})

    @app.post("/api/optimize")
    def api_optimize():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="expected a JSON object"), 400
        city_id = data.get("city_id")
        if not city_id:
            return jsonify(error="city_id is required"), 400
        city = cache.get_city(city_id)
        if city is None:
            return jsonify(error="city not found, load it first"), 400
        try:
            options = parse_options(data)
        except OptionError as exc:
            return jsonify(error=str(exc)), 400
        layout = load_layout_from_dict(city["payload"])
        try:
            job_id = jobs.submit(layout, **options)
        except JobBusy as exc:
            return jsonify(error=str(exc), active_job_id=exc.job_id), 409
        # Echo the resolved options so the client can show exactly what ran.
        return jsonify(job_id=job_id, options=options)

    @app.get("/api/stream/<job_id>")
    def api_stream(job_id):
        if not jobs.exists(job_id):
            return jsonify(error="unknown job"), 404

        def generate():
            while not jobs.is_done(job_id):
                imp = jobs.pop_improvement(job_id, timeout=0.2)
                if imp is not None:
                    yield f"event: improvement\ndata: {json.dumps(imp)}\n\n"
                else:
                    st = jobs.status(job_id)
                    yield f"event: heartbeat\ndata: {json.dumps(st)}\n\n"
            while True:
                imp = jobs.pop_improvement(job_id, timeout=0.05)
                if imp is None:
                    break
                yield f"event: improvement\ndata: {json.dumps(imp)}\n\n"
            # Terminal envelope: state (done | error), result, error, elapsed,
            # stopped -- one coherent snapshot, so an error is never a bare null.
            final = jobs.snapshot(job_id)
            yield f"event: done\ndata: {json.dumps(final, default=str)}\n\n"
        return Response(generate(), mimetype="text/event-stream")

    @app.post("/api/stop/<job_id>")
    def api_stop(job_id):
        if not jobs.exists(job_id):
            return jsonify(error="not found"), 404
        if not jobs.is_done(job_id):
            jobs.stop(job_id)
            return jsonify(ok=True)
        return jsonify(ok=True, already_done=True)

    @app.get("/api/cities")
    def api_cities_list():
        return jsonify(cache.list_cities())

    @app.get("/api/cities/<city_id>")
    def api_cities_get(city_id):
        city = cache.get_city(city_id)
        if city is None:
            return jsonify(error="not found"), 404
        return jsonify(city)

    @app.get("/api/cities/<city_id>/export")
    def api_cities_export(city_id):
        city = cache.get_city(city_id)
        if city is None:
            return jsonify(error="not found"), 404
        resp = Response(json.dumps(city["payload"]), mimetype="application/json")
        resp.headers["Content-Disposition"] = f'attachment; filename="{city_id}.city"'
        return resp

    @app.post("/api/cities/import")
    def api_cities_import():
        data = request.get_json(silent=True)
        if data is None:
            return jsonify(error="invalid JSON body"), 400
        try:
            return jsonify(_parse_and_cache(data))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.get("/api/layouts")
    def api_layouts_list():
        city_id = request.args.get("city_id")
        return jsonify(cache.list_layouts(city_id=city_id))

    @app.get("/api/layouts/<layout_id>")
    def api_layouts_get(layout_id):
        layout = cache.get_layout(layout_id)
        if layout is None:
            return jsonify(error="not found"), 404
        return jsonify(layout)

    @app.post("/api/layouts")
    def api_layouts_save():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="expected a JSON object"), 400
        city_id = data.get("city_id")
        if not city_id:
            return jsonify(error="city_id is required"), 400
        if cache.get_city(city_id) is None:
            return jsonify(error="city not found"), 400
        try:
            k, achieved, roads_count = (int(data.get(f, 0))
                                        for f in ("k", "achieved", "roads_count"))
        except (TypeError, ValueError, OverflowError):
            return jsonify(error="k, achieved and roads_count must be integers"), 400
        layout_json = data.get("layout_json", {})
        if not isinstance(layout_json, dict):
            return jsonify(error="layout_json must be an object"), 400
        layout_id = uuid.uuid4().hex[:12]
        cache.store_layout(layout_id, city_id, k, achieved, layout_json, roads_count)
        return jsonify(id=layout_id)

    @app.delete("/api/layouts/<layout_id>")
    def api_layouts_delete(layout_id):
        ok = cache.delete_layout(layout_id)
        if ok:
            return jsonify(ok=True)
        return jsonify(error="not found"), 404

    @app.get("/assets/<path:filename>")
    def spa_assets(filename):
        return send_from_directory(os.path.join(_DIST, "assets"), filename)

    @app.get("/<path:path>")
    def spa_fallback(path):
        if path.startswith("api/"):
            return jsonify(error="not found"), 404
        full = os.path.join(_DIST, path)
        if os.path.isfile(full):
            return send_from_directory(_DIST, path)
        if not os.path.exists(os.path.join(_DIST, "index.html")):
            return jsonify(error="frontend not built; run `npm run build` in frontend/"), 503
        return send_from_directory(_DIST, "index.html")

    return app


if __name__ == "__main__":
    create_app().run(port=5000, debug=False)
