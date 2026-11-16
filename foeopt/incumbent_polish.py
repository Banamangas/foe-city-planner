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
                                skeleton_parents, validate)

MAX_SOLVES = 2  # rebase again only after an accepted improvement


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


def _solve(search, pat, region, consumers, pos, fillers, limit, threads):
    """One rebased objective solve plus validate; (None, None, None) if the
    solver returned nothing. Filler positions in `pos` are only hints."""
    odiag: dict = {}
    opos = minimize_needed(pat, region, consumers, pos, limit=limit,
                           workers=threads, model="position", diag=odiag,
                           fillers=fillers, closure=getattr(search, "closure", "bfs"))
    if opos is None:
        return None, None, None
    return validate(search.layout, pat, opos,
                    exact_repair=min(search.exact_repair, limit),
                    exact_workers=threads,
                    witness=odiag.get("witness")
                    if getattr(search, "road_witness", False) else None)


def polish_rebased(search, incumbent: Layout, achieved: int, end: float,
                   on_improvement=None, should_stop=None, k=None) -> dict:
    """Up to MAX_SOLVES rebased objective solves before `end` (monotonic).
    `search` is the RoadsFirstSearch (layout, workers, probe_model, repair)."""
    region = set(search.layout.region.cells)
    consumers = search.layout.road_needing()
    threads = max(1, search.workers * search.probe_workers)
    report = {"before": achieved, "after": achieved, "attempts": []}
    seen: set = set()
    cur, cur_ach = incumbent, achieved
    for _ in range(MAX_SOLVES):
        if should_stop is not None and should_stop():
            break
        limit = end - time.monotonic() - OBJECTIVE_MARGIN_S
        if limit < OBJECTIVE_MIN_S:
            break
        pat = rebase_pattern(cur)
        if pat.roads in seen:
            break
        seen.add(pat.roads)
        all_fillers = model_fillers(search.layout, True, "position")
        first = all_fillers if getattr(search, "fillers_in_model", False) else None
        pos = incumbent_positions(search.layout, cur)
        # filler positions only hint the model-placed solve
        fpos = (incumbent_positions(search.layout, cur, all_fillers) or pos) if all_fillers else pos
        row = {"roads": len(pat.roads), "before": cur_ach, "after": None,
               "limit_s": round(limit, 1)}
        report["attempts"].append(row)
        if pos is None or not hint_is_feasible(search.layout, pat, pos):
            row["skipped"] = "hint"
            break
        t0 = time.monotonic()
        vst, vlay, vach = _solve(search, pat, region, consumers,
                                 fpos if first else pos, first, limit, threads)
        if vst == "SAT_FILLER_FAIL" and first is None and all_fillers:
            # Fast path first; when the fillers no longer fit, re-solve with them
            # placed by the model (slower, but a SAT always leaves them room).
            # FR24 2026-11-13: the fast path gave 232 -> 220, then a filler failure.
            left = end - time.monotonic() - OBJECTIVE_MARGIN_S
            row["filler_retry"] = True
            if left >= OBJECTIVE_MIN_S:
                vst, vlay, vach = _solve(search, pat, region, consumers, fpos,
                                         all_fillers, left, threads)
        row["solve_s"] = round(time.monotonic() - t0, 1)
        if vst is None:
            break
        row["status"] = vst
        if vst != "OK":
            break
        row["after"] = vach
        if vach >= cur_ach:
            break
        cur, cur_ach = vlay, vach
        report["after"] = vach
        if on_improvement is not None:
            on_improvement(vlay, k, vach)
    return report
