"""Paired benchmark harness for the roads-first engine (backlog item I1).

    # run: BEST_PRESET vs BEST_PRESET + one override, 2 paired reps, 120 s and 600 s
    .venv/bin/python scripts/bench.py run --name s2 \
        --arm preset --arm "par:parallel_polish=true" \
        --cities darkzig,FR16,FR17 --box 120,600 --reps 2

    # report an existing file (or several) against a base arm
    .venv/bin/python scripts/bench.py report output/bench/2026-11-16-s2/runs.jsonl --base preset

Rules it enforces (tasks/todo.md, "Rules for every agent"):
- **One timed run at a time on this machine.** CP-SAT limits are wall-clock, so two
  concurrent benchmarks corrupt each other. `run` holds an exclusive flock on
  `output/bench/.lock` for its whole duration; a second invocation waits (or fails
  with --no-wait). Code and unit tests do not need the lock.
- Arms are interleaved inside each (city, box, rep) cell, so slow drift hits all arms.
- Every arm starts from BEST_PRESET; `name:key=val;key=val` overrides it. Values are
  parsed as JSON when possible (true, 3, 0.5, "x", [3,4]), otherwise kept as strings.
  Unknown keys go straight to RoadsFirstSearch, so a new option needs no harness change.
- Every best layout is re-verified (full legality on the delivered roads, reroute,
  exact route, rotation, inventory, overlap) and saved; a count that fails is not a
  result (`accepted: false`).
- Verdict: adopt only if the arm is never worse than the base in any pair and better
  in at least one (lower roads; "none" is worse than any number).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import fcntl
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CITIES = {
    "darkzig": ("darkzig.json",),
    "FR16": ("CityMap-Born-FR16-2026-07-07.json",),
    "FR17": ("CityMap-Born-FR17-2026-07-07.json",),
    "FR24": ("CityMap-Born-FR24-2026-07-07.json",),
    "user": ("city-user-data.json", "city-user-data-foe-helper.json"),
    "agrou": ("agrou-city.json",),
}
# FoE Helper v3 exports (2026-11-17), kept untracked under cities/ (they carry
# player names). Benchmark name = file stem, e.g. --cities bigw,kosova.
CITIES.update({p.stem: (f"cities/{p.name}",)
               for p in sorted((pathlib.Path(__file__).resolve().parents[1] / "cities").glob("*.json"))})
MILITARY = "connect"
# harness-level defaults the webapp also uses for BEST_PRESET runs
BASE_KWARGS = {"workers": 6, "probe_workers": 2}


def _shared_root() -> pathlib.Path:
    """The MAIN checkout, also when running from a git worktree, so every
    worktree takes the same machine lock (one CPU budget, one lock)."""
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return pathlib.Path(common).parent if common else ROOT


LOCK = _shared_root() / "output" / "bench" / ".lock"
_CACHE: dict = {}


# ---------------------------------------------------------------- arms / options

def _value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_arm(spec: str) -> tuple[str, dict]:
    """'preset' -> ('preset', {}); 'x:a=1;b=true' -> ('x', {'a': 1, 'b': True})."""
    name, _, rest = spec.partition(":")
    over = {}
    for part in filter(None, (p.strip() for p in rest.split(";"))):
        key, eq, raw = part.partition("=")
        if not eq:
            raise SystemExit(f"bad override {part!r} in arm {spec!r} (want key=value)")
        over[key.strip()] = _value(raw.strip())
    return name.strip(), over


def search_kwargs(over: dict, box: float) -> dict:
    """BEST_PRESET + overrides, translated to RoadsFirstSearch kwargs the way
    webapp/runner.py does (string ranges -> tuples)."""
    from webapp.params import BEST_PRESET
    opts = {**BASE_KWARGS, **BEST_PRESET, **over}
    band = opts.get("quality_index_band")
    if isinstance(band, str):
        opts["quality_index_band"] = tuple(int(x) for x in band.split(",")) if band else None
    elif isinstance(band, list):
        opts["quality_index_band"] = tuple(band)
    modes = opts.get("comb_modes")
    if isinstance(modes, str):
        opts["comb_modes"] = tuple(m for m in modes.split(",") if m) or None
    pitches = opts.get("lane_pitches")
    if isinstance(pitches, str):
        opts["lane_pitches"] = tuple(int(x) for x in pitches.split(",") if x) or None
    opts.setdefault("military", MILITARY)
    opts["time_box"] = box
    return opts


# ---------------------------------------------------------------- run one cell

def city(name):
    from foeopt.loader import load_layout
    if name not in _CACHE:
        files = CITIES[name]
        missing = [f for f in files if not (ROOT / f).exists()]
        if missing:
            raise SystemExit(f"city {name}: missing input file(s) {missing}")
        _CACHE[name] = load_layout(*(str(ROOT / f) for f in files))
    return _CACHE[name]


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def manifest(name: str, kwargs: dict) -> dict:
    import ortools
    from foeopt.legality import LEGALITY_VERSION
    h = hashlib.sha256()
    for f in CITIES[name]:
        h.update((ROOT / f).read_bytes())
    return {"git_rev": _git("rev-parse", "--short", "HEAD"),
            "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "input_sha256": h.hexdigest()[:16], "rules_version": LEGALITY_VERSION,
            "ortools": ortools.__version__, "cpus": os.cpu_count(),
            "effective_options": {k: (list(v) if isinstance(v, tuple) else v)
                                  for k, v in kwargs.items()}}


def verify(src, lay) -> dict:
    """Independent re-check of a delivered layout. `legality` is computed on the
    roads AS DELIVERED; the reroute/exact counts are reported alongside."""
    from foeopt.exact_router import exact_route
    from foeopt.legality import check
    from foeopt.router import route
    from foeopt.validate import canonical_dims, is_valid, rotated_buildings
    ids_src = sorted(b.entity_id for b in src.buildings)
    ids = sorted(b.entity_id for b in lay.buildings)
    cells = [c for b in lay.buildings for c in b.footprint.cells()]
    region = src.region.cells
    lane = {c: lvl for c, lvl in lay.roads.items() if lvl >= 2} or None
    out = {"roads_delivered": len(lay.roads)}
    rep = check(lay, src, military=MILITARY)
    out.update(legality=rep.status, violations=rep.violations[:5])
    try:
        r = route(lay, fixed=lane)
        chk = type(lay)(lay.region, lay.buildings, lay.townhall, r)
        out.update(route=len(r), valid_reroute=is_valid(chk))
    except Exception as exc:                       # informational only
        out.update(route=None, route_error=f"{type(exc).__name__}: {exc}")
    try:
        er = exact_route(lay, time_limit=60, **({"fixed": lane} if lane else {}))
        out.update(exact=er.count, exact_optimal=er.optimal)
    except Exception as exc:
        out.update(exact=None, exact_error=f"{type(exc).__name__}: {exc}")
    out.update(rotated=len(rotated_buildings(lay, canonical_dims(src))),
               inventory_ok=ids == ids_src,
               overlap=len(cells) - len(set(cells)),
               out_of_region=sum(1 for c in cells if c not in region),
               on_road=sum(1 for c in cells if c in lay.roads))
    return out


def run_cell(arm: str, over: dict, name: str, box: float, rep: int, outdir: pathlib.Path) -> dict:
    from foeopt.roads_first import RoadsFirstSearch
    lay = city(name)
    kwargs = search_kwargs(over, box)
    rec = {"arm": arm, "overrides": over, "city": name, "box": box, "rep": rep,
           "started": _dt.datetime.now().isoformat(timespec="seconds"),
           "manifest": manifest(name, kwargs)}
    best = {"achieved": None, "layout": None, "k": None, "t": None}
    events = []
    t0 = time.monotonic()

    def on_imp(best_layout, k, achieved):
        t = round(time.monotonic() - t0, 1)
        events.append([t, achieved])
        rec.setdefault("first_s", t)
        if best["achieved"] is None or achieved < best["achieved"]:
            best.update(achieved=achieved, layout=best_layout, k=k, t=t)

    try:
        res = RoadsFirstSearch(lay, **kwargs).run(on_improvement=on_imp)
        rec["search_s"] = round(time.monotonic() - t0, 1)
        rec.update(ok=True, best=res.get("best_achieved"), verdict=res.get("verdict"),
                   best_k=best["k"], best_t=best["t"], improvements=events,
                   levels={str(k): v[0] for k, v in (res.get("results") or {}).items()},
                   profile=res.get("profile"),
                   objective_polish=res.get("objective_polish"),
                   rebased_polish=res.get("rebased_polish"),
                   exact_finish=res.get("exact_finish"),
                   seed_input=res.get("seed_input"))
        # seed_input publishes the uploaded city at t=0; the first layout the
        # SOLVER made is the next event (None if it never beat the upload)
        seeded = bool((res.get("seed_input") or {}).get("used"))
        walk = events[1:] if seeded else events
        rec["first_solver_s"] = walk[0][0] if walk else None
        if best["layout"] is not None:
            v = rec["verify"] = verify(lay, best["layout"])
            rec["accepted"] = (v["legality"] == "valid" and v["rotated"] == 0
                               and v["inventory_ok"] and v["overlap"] == 0
                               and v["roads_delivered"] == best["achieved"])
            fn = outdir / f"{name}-{arm}-b{int(box)}-r{rep}-a{best['achieved']}.json"
            fn.write_text(json.dumps({
                "city": name, "arm": arm, "box": box, "rep": rep,
                "achieved": best["achieved"], "k": best["k"],
                "manifest": rec["manifest"],
                "roads": sorted([x, y, lvl] for (x, y), lvl in best["layout"].roads.items()),
                "buildings": {b.entity_id: [b.footprint.x, b.footprint.y,
                                            b.footprint.width, b.footprint.length]
                              for b in best["layout"].buildings}}))
            rec["layout_file"] = str(fn.relative_to(ROOT))
    except Exception as exc:
        rec.update(ok=False, error=f"{type(exc).__name__}: {exc}",
                   traceback=traceback.format_exc()[-2000:])
    rec["wall_s"] = round(time.monotonic() - t0, 1)
    rec["overrun_x"] = round(rec["wall_s"] / box, 2)
    return rec


# ---------------------------------------------------------------- lock

@contextlib.contextmanager
def machine_lock(wait: bool, label: str):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = LOCK.open("a+")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.seek(0)
            holder = fh.read().strip() or "unknown"
            if not wait:
                raise SystemExit(f"bench lock held by: {holder}")
            print(f"bench lock held by: {holder} -- waiting", flush=True)
            fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()} {label} since {_dt.datetime.now():%Y-%m-%d %H:%M:%S}\n")
        fh.flush()
        yield
    finally:
        with contextlib.suppress(Exception):
            fh.seek(0)
            fh.truncate()
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


# ---------------------------------------------------------------- report

def _score(rec):
    """Comparable roads: accepted best, else None (= no result)."""
    if not rec.get("ok") or rec.get("best") is None:
        return None
    if rec.get("accepted") is False:
        return None
    return rec["best"]


def _cmp(a, b):
    """-1 if a better than b, 0 tie, 1 worse (lower roads better, None worst)."""
    if a == b:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    return -1 if a < b else 1


def report(rows: list[dict], base: str | None = None) -> str:
    arms = list(dict.fromkeys(r["arm"] for r in rows))
    base = base or arms[0]
    cells: dict = {}
    for r in rows:
        cells.setdefault((r["city"], r["box"], r["rep"]), {})[r["arm"]] = r
    lines = []
    head = f"{'city':8} {'box':>5} {'rep':>3} | " + " | ".join(f"{a:>14}" for a in arms)
    lines += [head, "-" * len(head)]
    for (c, box, rep) in sorted(cells, key=lambda k: (k[0], k[1], k[2])):
        row = cells[(c, box, rep)]
        out = []
        for a in arms:
            r = row.get(a)
            if r is None:
                out.append(f"{'-':>14}")
                continue
            s = _score(r)
            tag = "" if r.get("accepted", True) else "!"
            first = r.get("first_solver_s", r.get("first_s"))
            txt = f"{s if s is not None else 'none'}{tag}"
            if first is not None:
                txt += f" f{first:.0f}s"
            out.append(f"{txt:>14}")
        lines.append(f"{c:8} {int(box):>5} {rep:>3} | " + " | ".join(out))
    lines.append("")
    for a in arms:
        if a == base:
            continue
        better = worse = ties = 0
        for row in cells.values():
            if a in row and base in row:
                d = _cmp(_score(row[a]), _score(row[base]))
                better += d < 0
                worse += d > 0
                ties += d == 0
        verdict = "ADOPT" if worse == 0 and better > 0 else (
            "NEUTRAL" if worse == 0 else "REJECT")
        lines.append(f"{a} vs {base}: better {better}, worse {worse}, tie {ties} -> {verdict}")
    lines.append("('!' = failed verification, counted as no result; f = first solver layout time)")
    return "\n".join(lines)


def load_rows(paths) -> list[dict]:
    rows = []
    for p in paths:
        for line in pathlib.Path(p).read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("--name", required=True, help="experiment name (output dir suffix)")
    pr.add_argument("--arm", action="append", required=True,
                    help="'preset' or 'name:key=val;key=val' (repeatable)")
    pr.add_argument("--cities", default="darkzig,FR16,FR17")
    pr.add_argument("--box", default="120,600", help="comma-separated time boxes (s)")
    pr.add_argument("--reps", type=int, default=2)
    pr.add_argument("--out", default=None, help="JSONL path (default under output/bench)")
    pr.add_argument("--no-wait", action="store_true", help="fail if the lock is held")
    pp = sub.add_parser("report")
    pp.add_argument("files", nargs="+")
    pp.add_argument("--base", default=None)
    args = p.parse_args(argv)

    if args.cmd == "report":
        print(report(load_rows(args.files), args.base))
        return

    arms = [parse_arm(a) for a in args.arm]
    if len({a for a, _ in arms}) != len(arms):
        raise SystemExit("arm names must be unique")
    cities = [c for c in args.cities.split(",") if c]
    for c in cities:
        if c not in CITIES:
            raise SystemExit(f"unknown city {c!r}; known: {', '.join(CITIES)}")
    boxes = [float(b) for b in args.box.split(",") if b]
    outdir = ROOT / "output" / "bench" / f"{_dt.date.today():%Y-%m-%d}-{args.name}"
    outdir.mkdir(parents=True, exist_ok=True)
    out = pathlib.Path(args.out) if args.out else outdir / "runs.jsonl"
    # order: box, rep, city, arm -- the short box finishes first and arms interleave
    cells = [(box, rep, c, a, o) for box in boxes for rep in range(args.reps)
             for c in cities for a, o in arms]
    total = sum(c[0] for c in cells)
    with machine_lock(not args.no_wait, f"bench {args.name}"):
        print(f"{len(cells)} cells, {total / 60:.0f} min of boxes. SEQUENTIAL. -> {out}",
              flush=True)
        t0 = time.monotonic()
        with out.open("a") as fh:
            for i, (box, rep, c, a, o) in enumerate(cells, 1):
                print(f"[{i}/{len(cells)}] {c} box={int(box)} rep{rep} {a} "
                      f"(elapsed {(time.monotonic() - t0) / 60:.0f}m)", flush=True)
                rec = run_cell(a, o, c, box, rep, outdir)
                fh.write(json.dumps(rec, default=str) + "\n")
                fh.flush()
                v = rec.get("verify") or {}
                print(f"    -> best={rec.get('best')} accepted={rec.get('accepted')} "
                      f"first={rec.get('first_solver_s')}s legality={v.get('legality')} "
                      f"wall={rec['wall_s']}s ({rec['overrun_x']}x)"
                      + ("" if rec.get("ok") else f" ERROR {rec.get('error')}"), flush=True)
    print()
    print(report(load_rows([out]), arms[0][0]))


if __name__ == "__main__":
    main()
