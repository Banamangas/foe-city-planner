"""Union polish (backlog Q2, 2026-11-16): re-solve the placement objective on
the UNION of several solved road networks that share the Townhall.

Why: objective polish and rebased polish can only keep a subset of ONE
skeleton, and the incumbents are locally optimal (T5 windows up to 20x20: no
gain). A union lets the objective keep the good half of network A and the good
half of network B, a non-local move neither polish can make.

How: the cells the best member does not use are SOFT (`minimize_needed(...,
soft=cells)`): each is a road, a building cell or empty, so unused union cells
cost no space; the best member's own network stays hard, as in rebased polish
(which runs next and frees what the result leaves unused). Connectivity is the
exact "flow" closure ("layered" can reject the best member's own network,
because the union's shortcuts change BFS distances). The best member is a
COMPLETE hint (placement, roads and flow), so the solve starts feasible.

Measured offline 2026-11-16 (scripts/exp_union_polish.py, flow, 12-25 s per
solve): no union beat its best member or plain rebased polish on darkzig, FR16
or FR17, including unions with freshly generated same-TH networks that add
24-67 cells. FR16 and FR17 unions are mostly PROVEN optimal at 67 / 103;
darkzig unions with 48-67 new cells end FEASIBLE with weak bounds (0-34).

Members: the incumbent plus every network objective polish validated, grouped
by identical TH footprint. Unions tried, best first: the top-M members of each
group; the incumbent with each other member of its group; the incumbent with
its own original skeleton (when known). Every result goes through `validate`
(route, witness, fillers) and the full legality gate, and is published only if
strictly better than the incumbent.
"""
from __future__ import annotations

import time

from foeopt.incumbent_polish import incumbent_positions
from foeopt.legality import check as legality_check
from foeopt.model import Layout
from foeopt.roads_first import (OBJECTIVE_MARGIN_S, OBJECTIVE_MIN_S, Pattern,
                                minimize_needed, model_fillers, validate)

MAX_ANCHORS = 150_000   # anchor literals; a bigger union is skipped and logged
MAX_UNIONS = 6          # attempts per run


def th_key(lay: Layout) -> tuple:
    fp = lay.townhall.footprint
    return (fp.x, fp.y, fp.width, fp.length)


def union_pattern(members: list[Layout], extra_cells=()) -> Pattern:
    """Pattern = shared TH + the union of the members' road cells (and
    `extra_cells`, e.g. an original skeleton). All members share the TH."""
    keys = {th_key(m) for m in members}
    if len(keys) != 1:
        raise ValueError(f"members do not share a TH: {sorted(keys)}")
    th = members[0].townhall.footprint
    cells = set(extra_cells)
    for m in members:
        cells |= set(m.roads)
    return Pattern(th=th, roads=frozenset(cells - th.cells()),
                   params={"union": len(members)})


def plan_unions(members: list[tuple[int, Layout, Pattern | None]], incumbent: Layout,
                m: int = 3, max_unions: int = MAX_UNIONS) -> list[dict]:
    """The unions to try, best first. `members` are (achieved, layout, original
    skeleton or None); duplicates (same road set) are dropped. Each plan is
    {"kind", "members": [Layout, ...] best first, "extra": cells}."""
    seen: dict = {}
    uniq = []
    for ach, lay, pat in sorted(members, key=lambda t: t[0]):
        key = frozenset(lay.roads)
        if key in seen:                    # same network: keep a known skeleton
            i = seen[key]
            if uniq[i][2] is None and pat is not None:
                uniq[i] = (uniq[i][0], uniq[i][1], pat)
            continue
        seen[key] = len(uniq)
        uniq.append((ach, lay, pat))
    groups: dict[tuple, list] = {}
    for t in uniq:
        groups.setdefault(th_key(t[1]), []).append(t)
    inc_key = frozenset(incumbent.roads)
    plans, done = [], set()

    def add(kind, mem, extra=frozenset()):
        cells = frozenset().union(*(frozenset(x.roads) for x in mem), extra)
        if cells in done or (len(mem) < 2 and not (extra - frozenset(mem[0].roads))):
            return
        done.add(cells)
        plans.append({"kind": kind, "members": mem, "extra": extra})

    inc_group = groups.get(th_key(incumbent), [])
    # 1) the top-M networks of every TH group (the incumbent's group first)
    for key in sorted(groups, key=lambda k: (k != th_key(incumbent), groups[k][0][0])):
        g = groups[key]
        if len(g) >= 2:
            add(f"top{min(m, len(g))}", [t[1] for t in g[:m]])
    # 2) the incumbent with each other member of its group
    others = [t for t in inc_group if frozenset(t[1].roads) != inc_key]
    for t in others:
        add("inc+1", [incumbent, t[1]])
    # 3) the incumbent with its own original skeleton (route() may leave it)
    for ach, lay, pat in inc_group:
        if frozenset(lay.roads) == inc_key and pat is not None:
            add("inc+skeleton", [incumbent], frozenset(pat.roads))
            break
    return plans[:max_unions]


def solve_union(search, plan: dict, *, limit: float, threads: int,
                closure: str = "flow", max_anchors: int = MAX_ANCHORS,
                soft: str = "new") -> tuple[dict, Layout | None]:
    """One union solve + validate + legality. Returns (telemetry row, layout or
    None). The layout is legal; the caller decides whether it is better.

    `soft`: "new" makes only the cells the best member does NOT use soft (its
    own network stays hard, as in rebased polish, which runs next and frees
    whatever the result leaves unused); "all" makes every union cell soft
    (measured 2026-11-16 on darkzig: 3x the anchors, a bound of 20 against an
    objective of 88, no move from the hint in 20 s)."""
    members = plan["members"]
    best = members[0]
    pat = union_pattern(members, plan["extra"])
    region = set(search.layout.region.cells)
    consumers = search.layout.road_needing()
    fillers = model_fillers(search.layout, getattr(search, "fillers_in_model", False),
                            "position")
    row = {"kind": plan["kind"], "members": [len(x.roads) for x in members],
           "union_cells": len(pat.roads),
           "new_cells": len(set(pat.roads) - set(best.roads)), "limit_s": round(limit, 1)}
    pos = incumbent_positions(search.layout, best, fillers or None)
    if pos is None:
        row["status"] = "NO_HINT"
        return row, None
    diag: dict = {}
    t0 = time.monotonic()
    opos = minimize_needed(pat, region, consumers, pos, limit=limit, workers=threads,
                           model="position", diag=diag, fillers=fillers,
                           closure=closure,
                           soft=True if soft == "all" else frozenset(pat.roads) - set(best.roads),
                           hint_roads=set(best.roads),
                           max_anchors=max_anchors)
    row.update(solve_s=round(time.monotonic() - t0, 1),
               status=diag.get("objective_status"), objective=diag.get("objective"),
               bound=diag.get("objective_bound"), model_size=diag.get("model_size"))
    if opos is None:
        return row, None
    vst, vlay, vach = validate(search.layout, pat, opos,
                               exact_repair=min(getattr(search, "exact_repair", 0.0), limit),
                               exact_workers=threads,
                               witness=diag.get("witness")
                               if getattr(search, "road_witness", False) else None)
    row["validate"] = vst
    if vst != "OK":
        return row, None
    row["after"] = vach
    src = getattr(search, "source_layout", search.layout)
    rep = legality_check(vlay, src, military=getattr(search, "military", "connect"),
                         off_road=getattr(search, "off_road", frozenset()))
    row["legality"] = rep.status
    if rep.status != "valid":
        return row, None
    return row, vlay


def polish_union(search, incumbent: Layout, achieved: int, end: float,
                 members: list[tuple[int, Layout, Pattern | None]],
                 on_improvement=None, should_stop=None, k=None) -> dict:
    """Try the planned unions before `end` (monotonic), splitting the time left
    evenly over the unions still to go. Publishes strict improvements only."""
    t_start = time.monotonic()
    threads = (search._polish_threads() if hasattr(search, "_polish_threads")
               else max(1, search.workers * search.probe_workers))
    # Always flow: the union's shortcuts change BFS distances, so "layered" can
    # reject the best member's own network (measured 2026-11-16, darkzig
    # 88 + a 97 member: the hint became infeasible and the solve returned 96).
    closure = "flow"
    allm = [(achieved, incumbent, None), *members]
    plans = plan_unions(allm, incumbent, m=getattr(search, "union_m", 3))
    report = {"before": achieved, "after": achieved, "members": len(allm),
              "th_groups": len({th_key(t[1]) for t in allm}), "planned": len(plans),
              "closure": closure, "tried": []}
    cur = achieved
    for i, plan in enumerate(plans):
        if should_stop is not None and should_stop():
            break
        limit = (end - time.monotonic() - OBJECTIVE_MARGIN_S) / (len(plans) - i)
        if limit < OBJECTIVE_MIN_S:
            break
        row, lay = solve_union(search, plan, limit=limit, threads=threads,
                               closure=closure)
        report["tried"].append(row)
        if lay is not None and row["after"] < cur:
            cur = row["after"]
            report["after"] = cur
            if on_improvement is not None:
                on_improvement(lay, k, cur)
    report["time_s"] = round(time.monotonic() - t_start, 1)
    return report
