"""Rebased polish (Codex T4, 2026-11-12): re-solve the placement objective on
the incumbent's ACCEPTED road network instead of its original skeleton.

Objective polish (`RoadsFirstSearch._apply_objective_polish`) is where FR17's
103 is made, but it works on the original skeleton (e.g. k=116 cells), all of
which block consumers -- including the cells the accepted network (~103 roads)
no longer uses. Rebuilding the pattern from the incumbent's own roads frees
those cells as consumer anchors, and the incumbent placement is a known
feasible hint for the new model.

Limits: the new pattern is the incumbent network, so shrinking it can also
remove contact opportunities; an UNSAT or no-gain solve is a safe no-op, never a
proof about the city. Fillers are repacked by `validate`; the incumbent stays
published unless a fully validated strictly better layout is found.
"""
from __future__ import annotations

import time

from foeopt.model import Footprint, Layout, contact_cells
from foeopt.legality import two_lane_tiles
from foeopt.roads_first import (LANE_PREFIX, OBJECTIVE_MARGIN_S, OBJECTIVE_MIN_S,
                                Pattern, minimize_needed, model_fillers,
                                report_layout, skeleton_parents, validate)

MAX_SOLVES = 2  # rebase again only after an accepted improvement
# Q4 (`iterate`): each consumer-only solve gets at most ITER_SLICE_S. FR24
# 2026-11-17: that solve reaches ~220 every time (31-62 s OPTIMAL, or 197 s
# FEASIBLE when unbounded) but the fillers then fail to fit, also with 3 other
# seeds; the model-filler solve got 232 -> 229/230 in 57-134 s (bound ~50). So
# on a filler failure the solve's earlier, less tight improving solutions (its
# trail) are validated best first, before the model-filler retry.
ITER_SLICE_S = 60.0


def rebase_pattern(incumbent: Layout) -> Pattern:
    """The incumbent's own Townhall and saved road cells, as a skeleton."""
    return Pattern(th=incumbent.townhall.footprint,
                   roads=frozenset(incumbent.roads), params={"rebased": True})


def incumbent_positions(search_layout: Layout, incumbent: Layout,
                        fillers=None) -> dict | None:
    """Positions dict (as `probe` returns) of the incumbent, keyed like the
    search layout's consumers. A composite chain sits at its first member's
    position minus that member's offset. The two-lane tile, if any, becomes
    "lane2:0". `fillers` (Phase D) are added the same way. None if a building
    cannot be found in the incumbent."""
    where = {b.entity_id: b.footprint for b in incumbent.buildings}
    pos: dict = {}
    for b in [*search_layout.road_needing(), *(fillers or ())]:
        w, l = b.footprint.width, b.footprint.length
        if b.members:
            m, dx, dy = b.members[0]
            fp = where.get(m.entity_id)
            if fp is None:
                return None
            pos[b.entity_id] = (fp.x - dx, fp.y - dy, w, l)
        else:
            fp = where.get(b.entity_id)
            if fp is None:
                return None
            pos[b.entity_id] = (fp.x, fp.y, w, l)
    tiles = two_lane_tiles(incumbent.roads) or []
    for i, (tx, ty) in enumerate(tiles):
        pos[f"{LANE_PREFIX}{i}"] = (tx, ty, 2, 2)
    return pos


def hint_is_feasible(search_layout: Layout, pattern: Pattern, positions: dict) -> bool:
    """Every one-lane consumer touches a TH-reachable road of `pattern` through
    its contact cells, and no consumer covers a road or the TH. (Two-lane
    consumers are checked by the model's tile constraint.)"""
    reach = set(skeleton_parents(pattern))
    blocked = set(pattern.roads) | set(pattern.th.cells())
    for b in search_layout.road_needing():
        x, y, w, l = positions[b.entity_id]
        if Footprint(x, y, w, l).cells() & blocked:
            return False
        if b.road_level < 2 and not (contact_cells(b, x, y) & reach):
            return False
    return True


def _solve(search, pat, region, consumers, pos, fillers, limit, threads, tele=None,
           trail=None):
    """One rebased objective solve plus validate; (None, None, None) if the
    solver returned nothing. Filler positions in `pos` are only hints.
    `tele` (a list) gets one telemetry dict per call."""
    odiag: dict = {} if trail is None else {"trail": trail}
    t0 = time.monotonic()
    opos = minimize_needed(pat, region, consumers, pos, limit=limit,
                           workers=threads, model="position", diag=odiag,
                           fillers=fillers, closure=getattr(search, "closure", "bfs"))
    if tele is not None:
        tele.append({"fillers": bool(fillers), "limit_s": round(limit, 1),
                     "objective_status": odiag.get("objective_status"),
                     "objective_s": odiag.get("objective_s"),
                     "objective": odiag.get("objective"),
                     "bound": odiag.get("objective_bound")})
    if opos is None:
        return None, None, None
    out = validate(search.layout, pat, opos,
                   exact_repair=min(search.exact_repair, limit),
                   exact_workers=threads,
                   witness=odiag.get("witness")
                   if getattr(search, "road_witness", False) else None)
    if tele is not None:
        tele[-1].update(status=out[0], roads=out[2],
                        wall_s=round(time.monotonic() - t0, 1))
    return out


def _from_trail(search, pat, trail, cur_ach, end, threads, row):
    """Validate the solve's earlier improving solutions (one per objective
    value, best first; the final one already failed) until one keeps the
    fillers and beats `cur_ach`. Returns validate's triple, or a filler
    failure when none does."""
    last: dict = {}
    for obj, pos, wit in trail[:-1]:
        last[obj] = (pos, wit)          # the last solution of each value
    tried = 0
    out = ("SAT_FILLER_FAIL", None, None)
    for obj in sorted(o for o in last if o < cur_ach):
        left = end - time.monotonic() - OBJECTIVE_MARGIN_S
        if left < 1.0:
            break
        pos, wit = last[obj]
        tried += 1
        got = validate(search.layout, pat, pos,
                       exact_repair=min(search.exact_repair, left),
                       exact_workers=threads,
                       witness=wit if getattr(search, "road_witness", False) else None)
        if got[0] == "OK" and got[2] < cur_ach:
            out = got
            row["trail_ok_objective"] = obj
            break
    row["trail"] = {"solutions": len(trail), "values": len(last), "tried": tried}
    return out


def polish_rebased(search, incumbent: Layout, achieved: int, end: float,
                   on_improvement=None, should_stop=None, k=None,
                   iterate: bool | None = None) -> dict:
    """Rebased objective solves before `end` (monotonic). `search` is the
    RoadsFirstSearch (layout, workers, probe_model, repair).

    Default: up to MAX_SOLVES solves, each with the whole remaining window.
    `iterate` (Q4; default `search.rebase_iterate`) runs to a fixed point:
    rebase on every accepted improvement until a solve gains nothing or the
    deadline, with ITER_SLICE_S consumer-only solves; on a filler failure the
    solve's trail of earlier solutions is tried before the model-filler retry."""
    if iterate is None:
        iterate = bool(getattr(search, "rebase_iterate", False))
    region = set(search.layout.region.cells)
    consumers = search.layout.road_needing()
    threads = max(1, search.workers * search.probe_workers)
    report = {"before": achieved, "after": achieved, "attempts": [], "iterate": iterate}
    seen: set = set()
    cur, cur_ach = incumbent, achieved
    all_fillers = model_fillers(search.layout, True, "position")
    in_model = bool(getattr(search, "fillers_in_model", False)) and bool(all_fillers)
    solves = 0
    while iterate or solves < MAX_SOLVES:
        solves += 1
        if should_stop is not None and should_stop():
            report["stop"] = "should_stop"
            break
        limit = end - time.monotonic() - OBJECTIVE_MARGIN_S
        if limit < OBJECTIVE_MIN_S:
            report["stop"] = "deadline"
            break
        pat = rebase_pattern(cur)
        if pat.roads in seen:
            report["stop"] = "seen"
            break
        seen.add(pat.roads)
        pos = incumbent_positions(search.layout, cur)
        # filler positions only hint the model-placed solve
        fpos = (incumbent_positions(search.layout, cur, all_fillers) or pos) if all_fillers else pos
        row = {"roads": len(pat.roads), "before": cur_ach, "after": None,
               "limit_s": round(limit, 1), "solves": []}
        report["attempts"].append(row)
        if pos is None or not hint_is_feasible(search.layout, pat, pos):
            row["skipped"] = "hint"
            report["stop"] = "hint"
            break
        t0 = time.monotonic()
        vst = vlay = vach = None
        if in_model:
            vst, vlay, vach = _solve(search, pat, region, consumers, fpos,
                                     all_fillers, limit, threads, row["solves"])
        else:
            trail = [] if iterate else None
            vst, vlay, vach = _solve(search, pat, region, consumers, pos, None,
                                     min(limit, ITER_SLICE_S) if iterate else limit,
                                     threads, row["solves"], trail=trail)
            if vst == "SAT_FILLER_FAIL" and trail:
                vst, vlay, vach = _from_trail(search, pat, trail, cur_ach, end,
                                              threads, row)
            if vst == "SAT_FILLER_FAIL" and all_fillers:
                # Fast path first; when the fillers no longer fit, re-solve with
                # them placed by the model (slower, but a SAT always leaves them
                # room). FR24 2026-11-13: fast 232 -> 220, then a filler failure.
                left = end - time.monotonic() - OBJECTIVE_MARGIN_S
                row["filler_retry"] = True
                if left >= OBJECTIVE_MIN_S:
                    vst, vlay, vach = _solve(search, pat, region, consumers, fpos,
                                             all_fillers, left, threads, row["solves"])
        row["solve_s"] = round(time.monotonic() - t0, 1)
        if vst is None:
            report["stop"] = "no_solution"
            break
        row["status"] = vst
        if vst != "OK":
            report["stop"] = vst
            break
        row["after"] = vach
        report_layout(search, vlay, k, vach)
        if vach >= cur_ach:
            report["stop"] = "no_gain"
            break
        cur, cur_ach = vlay, vach
        report["after"] = vach
        if on_improvement is not None:
            on_improvement(vlay, k, vach)
    else:
        report["stop"] = "max_solves"
    report["unused_s"] = round(max(0.0, end - time.monotonic()), 1)
    return report
