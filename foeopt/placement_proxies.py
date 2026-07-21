"""Pure-Python placement proxies for the roads-first inner objective (Stage 0).

Each proxy scores a *finished* consumer placement against a road skeleton,
correlating (Stage 0 measures how well) with the post-route() road count. No
ortools/numpy — this stays importable in the pure-stdlib core and doubles as the
reference oracle for the later CP-SAT objective.

positions: dict[entity_id, (x, y, w, l)] — same shape probe()/validate() emit.
"""
from __future__ import annotations

from collections import deque

from foeopt.model import Footprint

Cell = tuple[int, int]
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def road_contacts(pattern, positions) -> dict[Cell, set[int]]:
    """Skeleton road cell -> set of entity_ids orthogonally adjacent to it."""
    roads = pattern.roads
    out: dict[Cell, set[int]] = {}
    for eid, (x, y, w, l) in positions.items():
        for c in Footprint(x, y, w, l).border_cells():
            if c in roads:
                out.setdefault(c, set()).add(eid)
    return out


def proxy_touched_cells(pattern, positions) -> int:
    """P1: number of distinct skeleton cells that carry >=1 consumer. Lower better."""
    return len(road_contacts(pattern, positions))


def _road_parents(pattern) -> dict[Cell, Cell | None]:
    """BFS parent map over skeleton road cells, rooted at road cells that touch
    the Townhall footprint. A cell's chain of parents is its path to the TH."""
    roads = set(pattern.roads)
    th_cells = set(pattern.th.cells())
    roots = [c for c in roads
             if any((c[0] + dx, c[1] + dy) in th_cells for dx, dy in _ORTHO)]
    parent: dict[Cell, Cell | None] = {r: None for r in roots}
    q = deque(roots)
    while q:
        c = q.popleft()
        for dx, dy in _ORTHO:
            nb = (c[0] + dx, c[1] + dy)
            if nb in roads and nb not in parent:
                parent[nb] = c
                q.append(nb)
    return parent


def proxy_subtree(pattern, positions) -> int:
    """P2: size of the connected skeleton subtree (touched cells + their
    connectors to the TH). Lower better. route() may still beat this, so it is an
    upper proxy the real router can only improve on."""
    parent = _road_parents(pattern)
    keep: set[Cell] = set()
    for c in road_contacts(pattern, positions):
        cur: Cell | None = c
        while cur is not None and cur not in keep:
            keep.add(cur)
            cur = parent.get(cur)
    return len(keep)


def proxy_double_loaded(pattern, positions) -> int:
    """P3: reward straight double-loaded rows. Count road cells serving >=2
    consumers, plus each collinear-adjacent pair of such cells (a run). Higher
    better."""
    contacts = road_contacts(pattern, positions)
    load2 = {c for c, ids in contacts.items() if len(ids) >= 2}
    runs = 0
    for (cx, cy) in load2:
        for dx, dy in ((1, 0), (0, 1)):  # forward-only so each pair counts once
            if (cx + dx, cy + dy) in load2:
                runs += 1
    return len(load2) + runs


def _lane_aligned(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, al = a
    bx, by, bw, bl = b
    same_col = ax == bx and aw == bw   # stacked in a vertical lane
    same_row = ay == by and al == bl   # in a row of a horizontal lane
    return same_col or same_row


def proxy_same_size_clusters(pattern, positions) -> int:
    """P4: reward same-footprint consumers aligned into a lane (shared column- or
    row-span). Clean double-loading needs equal-depth neighbours. Higher better."""
    by_size: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for (x, y, w, l) in positions.values():
        by_size.setdefault((w, l), []).append((x, y, w, l))
    score = 0
    for items in by_size.values():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if _lane_aligned(items[i], items[j]):
                    score += 1
    return score
