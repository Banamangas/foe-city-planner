from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid

from flask import Flask, Response, jsonify, request, send_from_directory

import foeopt.machine as machine
from foeopt.catalog import Catalog
from foeopt.editing import UNPLACEABLE_TYPES, EditError, apply_edits, loose_chain_pieces
from foeopt.export_v3 import ExportError, can_export, to_v3
from foeopt.loader import city_catalog_defs, is_v3, load_layout_from_dict, load_layout
from foeopt.report import road_estimate
from foeopt.stats import city_stats
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


def _v3_slim(data: dict) -> dict:
    """What the upload worker cached of a v3 file before plan X (its old
    stripV3, same key order): the part the optimizer reads. cityData keys go in
    JavaScript's order (integer-like keys ascending, then the rest as given),
    which is the order every browser upload arrived in, whatever the file's."""
    src = data.get("cityData") or {}
    ints = sorted((k for k in src if k.isdigit() and (k == "0" or k[0] != "0")), key=int)
    int_set = set(ints)
    keys = ints + [k for k in src if k not in int_set]
    city = {}
    for key in keys:
        e = src[key]
        out = {"id": e.get("id"), "cityentity_id": e.get("cityentity_id"), "type": e.get("type")}
        for c in ("x", "y"):
            if c in e:
                out[c] = e[c]
        city[key] = out
    slim = {"version": data.get("version"), "cityData": city, "mapData": data.get("mapData") or []}
    if "helper_data" in data:
        slim["helper_data"] = data["helper_data"]
    return slim


def city_id_for(data: dict) -> str:
    """A v3 city is identified by its slim part, so the full file (cached since
    plan X) gets the SAME id as its slim cache from before: re-uploading keeps
    the saved edits and layouts, and upgrades the cache to the full file."""
    return _city_hash(json.dumps(_v3_slim(data) if is_v3(data) else data).encode())


def _safe_stem(name: str | None, fallback: str) -> str:
    stem = os.path.splitext(os.path.basename(name or ""))[0]
    # ASCII only: the name goes into a Content-Disposition header.
    stem = "".join(ch for ch in stem
                   if ch.isascii() and (ch.isalnum() or ch in "-_. ")).strip()
    return stem or fallback


def _buildings_summary(layout, catalog: Catalog | None = None) -> list[dict]:
    """Per-building rows for the UI. The chain fields drive the edit panel
    (chain removal notices, the main-building picker for added patches)."""
    def head(b):
        return bool(b.chain_id) and catalog is not None and catalog.is_chain_head(b.cityentity_id)
    return [{
        "entity_id": b.entity_id, "name": b.name,
        "width": b.footprint.width, "length": b.footprint.length,
        "needs_road": b.needs_road, "is_townhall": b.is_townhall,
        "cityentity_id": b.cityentity_id, "chain_id": b.chain_id,
        "is_chain_head": head(b),
    } for b in layout.buildings]


MAX_CATALOG_RESULTS = 30


def _off_road(layout, keep: list[int]) -> frozenset[int]:
    """The requested ids of buildings in `layout` that need a road; removed,
    unknown and road-free ids are dropped."""
    needing = {b.entity_id for b in layout.road_needing()}
    return frozenset(i for i in keep if i in needing)


def _catalog_row(catalog: Catalog, cid: str) -> dict | None:
    etype = catalog.entity_type(cid)
    size = catalog.size(cid)
    if size is None or etype in UNPLACEABLE_TYPES or etype == "main_building":
        return None
    req = catalog.street_requirement(cid)
    chain = catalog.chain_id(cid)
    return {"id": cid, "name": catalog.name(cid), "type": etype,
            "width": size[0], "length": size[1], "needs_road": req > 0,
            "road_level": catalog.required_level(cid) if req > 0 else 0,
            "chain_id": chain, "is_chain_head": bool(chain) and catalog.is_chain_head(cid)}


def search_catalog(catalog: Catalog, q: str, limit: int = MAX_CATALOG_RESULTS) -> list[dict]:
    """Placeable catalog entries whose name or id contains `q` (case-insensitive).
    Name matches rank before id-only matches, prefix matches first."""
    ql = q.strip().lower()
    if not ql:
        return []
    hits = []
    for cid in catalog.ids():
        name = str(catalog.name(cid)).lower()
        in_name, in_id = ql in name, ql in cid.lower()
        if not (in_name or in_id):
            continue
        row = _catalog_row(catalog, cid)
        if row is not None:
            rank = 0 if name.startswith(ql) else 1 if in_name else 2
            hits.append((rank, len(name), name, cid, row))
    hits.sort(key=lambda h: h[:4])
    return [h[4] for h in hits[:limit]]


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=_DIST, static_url_path="/assets_root")
    cache = CityCache(db_path or os.path.join(os.path.dirname(__file__), "cities.db"))
    jobs = JobManager()

    def _save_tmp(file_storage) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        file_storage.save(path)
        return path

    def _parse_and_cache(data, helper_data: dict | None = None,
                         name: str | None = None) -> dict:
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        if helper_data is not None and ("entities" in data or is_v3(data)):
            # Split export: keep the helper's catalog INSIDE the cached payload
            # so later loads (optimize, export, re-import) still resolve sizes,
            # road levels and chains. Only CityEntities is needed.
            data = {**data, "helper_data": {"CityEntities": helper_data.get("CityEntities", {})}}
        layout = load_layout_from_dict(data)
        payload = json.dumps(data).encode()
        city_id = city_id_for(data)
        catalog = Catalog(city_catalog_defs(data))
        buildings = _buildings_summary(layout, catalog)
        stats = city_stats(layout)
        cache.store_city(city_id, payload, buildings,
                         len(layout.region.cells), road_estimate(layout), name=name)
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
            "stats": stats,
            # Load-time problems worth flagging to the player.
            "checks": {"unconnected": stats["unconnected"],
                       "loose_chain_pieces": loose_chain_pieces(layout, catalog)},
            # Edits saved for this city (survive a reload of the same file).
            "edits": cache.get_edits(city_id),
        }

    _catalogs: dict[str, Catalog] = {}

    def _catalog_for(city: dict) -> Catalog:
        cat = _catalogs.get(city["id"])
        if cat is None:
            cat = _catalogs[city["id"]] = Catalog(city_catalog_defs(city["payload"]))
        return cat

    def _edit_city(city: dict, edits, relink_chains: bool = False) -> tuple:
        """(edited layout, report) for a cached city, or raise EditError."""
        if not isinstance(edits, dict):
            raise EditError("edits must be an object {remove: [...], add: [...]}")
        layout = load_layout_from_dict(city["payload"])
        return apply_edits(layout, edits.get("remove") or [], edits.get("add") or [],
                           catalog=_catalog_for(city), relink=edits.get("relink") or {},
                           relink_loose=relink_chains)

    def _edit_error(exc: EditError):
        return jsonify(error=str(exc), **exc.detail), 400

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
            return jsonify(_parse_and_cache(data, name=request.args.get("name") or None))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.post("/api/load/raw")
    def api_load_raw():
        if "city" not in request.files:
            return jsonify(error="no city file"), 400
        city_name = request.files["city"].filename or None
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
            return jsonify(_parse_and_cache(data, helper_data, name=city_name))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.get("/api/options")
    def api_options():
        """Serve the run-parameter spec the Optimize panel renders itself from.

        webapp/params.py is the single source of truth: every knob, its type,
        range, default, help text and the CLI flag it mirrors.
        """
        return jsonify(options=OPTION_SPECS, groups=GROUP_LABELS,
                       presets={"smoke": SMOKE_PRESET, "best": BEST_PRESET},
                       machine=machine.machine_info())

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
        # Size parallelism to this machine unless the request chose it.
        sized = machine.machine_info()
        for key in ("workers", "probe_workers"):
            if key not in data:
                options[key] = sized[key]
        keep = data.get("keep_unconnected", [])
        if not isinstance(keep, list) or not all(
                isinstance(i, int) and not isinstance(i, bool) for i in keep):
            return jsonify(error="keep_unconnected must be a list of entity ids"), 400
        edits = data.get("edits")
        relink_chains = data.get("relink_chains", True) is not False
        layout = load_layout_from_dict(city["payload"])
        has_loose = relink_chains and bool(loose_chain_pieces(layout, _catalog_for(city)))
        if not has_loose and (not edits or (isinstance(edits, dict)
                                            and not edits.get("remove")
                                            and not edits.get("add"))):
            # Unedited city: exactly the historical path.
            try:
                job_id = jobs.submit(layout, off_road=_off_road(layout, keep), **options)
            except JobBusy as exc:
                return jsonify(error=str(exc), active_job_id=exc.job_id), 409
            # Echo the resolved options so the client can show exactly what ran.
            return jsonify(job_id=job_id, options=options)
        try:
            layout, report = _edit_city(city, edits or {}, relink_chains)
        except EditError as exc:
            return _edit_error(exc)
        space = report["space"]
        if not space["fits_without_roads"]:
            return jsonify(
                error=(f"the new buildings do not fit: they need {space['overflow']} more "
                       f"cells than the city has free, even with zero roads"),
                space=space, report=report), 400
        if report["not_composable"]:
            return jsonify(error="; ".join(w for w in report["warnings"]
                                           if "rigid block" in w),
                           report=report), 400
        # Every published result carries what leaves the map and what was added,
        # so the export lists the buildings to store.
        edit_info = {"to_store": report["to_store"], "added": report["added"]}
        try:
            job_id = jobs.submit(layout, edit_info=edit_info,
                                 off_road=_off_road(layout, keep), **options)
        except JobBusy as exc:
            return jsonify(error=str(exc), active_job_id=exc.job_id), 409
        return jsonify(job_id=job_id, options=options, edits=edits, report=report)

    @app.get("/api/catalog")
    def api_catalog():
        """Search placeable building types: the bundled catalog plus the
        city's own definitions when `city_id` names a cached city."""
        city_id = request.args.get("city_id")
        if city_id:
            city = cache.get_city(city_id)
            if city is None:
                return jsonify(error="city not found"), 404
            catalog = _catalog_for(city)
        else:
            catalog = Catalog(city_catalog_defs({}))
        return jsonify(results=search_catalog(catalog, request.args.get("q", "")))

    @app.post("/api/edits/preview")
    def api_edits_preview():
        """What an edit set would do, without running anything: buildings to
        store, chain reattachments, the space pre-check and the seed verdict."""
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data.get("city_id"):
            return jsonify(error="city_id is required"), 400
        city = cache.get_city(data["city_id"])
        if city is None:
            return jsonify(error="city not found, load it first"), 400
        try:
            _, report = _edit_city(city, data.get("edits") or {},
                                  data.get("relink_chains", True) is not False)
        except EditError as exc:
            return _edit_error(exc)
        return jsonify(report=report)

    @app.put("/api/cities/<city_id>/edits")
    def api_cities_edits(city_id):
        if cache.get_city(city_id) is None:
            return jsonify(error="not found"), 404
        edits = request.get_json(silent=True)
        if not isinstance(edits, dict):
            return jsonify(error="expected a JSON object"), 400
        cache.set_edits(city_id, edits)
        return jsonify(ok=True)

    @app.get("/api/stream/<job_id>")
    def api_stream(job_id):
        if not jobs.exists(job_id):
            return jsonify(error="unknown job"), 404

        def layout_events():
            # Every kept layout (webapp.collector), as soon as it is found.
            while (entry := jobs.pop_layout(job_id)) is not None:
                yield f"event: layout\ndata: {json.dumps(entry)}\n\n"

        def generate():
            while not jobs.is_done(job_id):
                imp = jobs.pop_improvement(job_id, timeout=0.2)
                yield from layout_events()
                if imp is not None:
                    yield f"event: improvement\ndata: {json.dumps(imp)}\n\n"
                else:
                    st = jobs.status(job_id)
                    yield f"event: heartbeat\ndata: {json.dumps(st)}\n\n"
            while True:
                imp = jobs.pop_improvement(job_id, timeout=0.05)
                yield from layout_events()
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

    def _export_v3(city: dict, layout_json):
        """Download the result as a v3 city file for Forge Hammer (plan X)."""
        if not isinstance(layout_json, dict):
            return jsonify(error="layout must be an object"), 400
        warnings: list[str] = []
        try:
            doc = to_v3(city["payload"], layout_json, layout_json.get("to_store") or [],
                        layout_json.get("added") or [], catalog=_catalog_for(city),
                        warnings=warnings)
        except ExportError as exc:
            return jsonify(error=str(exc),
                           reupload=not can_export(city["payload"])), 400
        stem = _safe_stem(city.get("name"), city["id"])
        resp = Response(json.dumps(doc), mimetype="application/json")
        resp.headers["Content-Disposition"] = f'attachment; filename="{stem}-optimized.json"'
        if warnings:
            resp.headers["X-Export-Warnings"] = json.dumps(warnings)   # ASCII-escaped
        return resp

    @app.post("/api/export/v3")
    def api_export_v3():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data.get("city_id"):
            return jsonify(error="city_id is required"), 400
        city = cache.get_city(data["city_id"])
        if city is None:
            return jsonify(error="city not found, load it first"), 400
        return _export_v3(city, data.get("layout"))

    @app.get("/api/layouts/<layout_id>/export.v3")
    def api_layouts_export_v3(layout_id):
        rec = cache.get_layout(layout_id)
        if rec is None:
            return jsonify(error="not found"), 404
        city = cache.get_city(rec["city_id"])
        if city is None:
            return jsonify(error="the layout's city is no longer cached"), 400
        return _export_v3(city, rec["layout"])

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
