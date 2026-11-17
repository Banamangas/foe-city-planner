"""N5 (2026-11-17): local mutations of a CONCRETE road skeleton.

Q3 found that the rooted family can express the expert networks but random
draws almost never land near one, so the bottleneck is sampling. This module
gives the moves for a directed search that starts from a good skeleton (the
best SAT skeleton or an incumbent's road network) and changes it a little:

    extend    grow a leaf straight on, 1..max_len cells
    shorten   cut 1..max_len cells back from a leaf (never past a junction)
    remove    drop a whole arm (leaf .. first junction or TH contact)
    shift     translate a straight arm sideways along its trunk
    add       grow a new straight arm off any road cell
    spoke     grow a new straight arm off a TH side no road touches
    merge     replace two parallel arms on one trunk by one in the middle
    prune     keep only the cells the objective's network used

Every operator is pure: (roads, th, region, rng, ...) -> frozenset | None, and
a non-None result always passes `roads_first._check_pattern` (inside the region,
off the TH, every cell connected to the TH border). Growth never touches a road
cell other than the one it grows from, so moves add no loops or 2x2 blocks.
Buildings are not involved here at all, so nothing can rotate.
"""
from __future__ import annotations

import random

from foeopt.model import Footprint

Cell = tuple[int, int]
ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _add(c: Cell, d: Cell, s: int = 1) -> Cell:
    return (c[0] + s * d[0], c[1] + s * d[1])


def road_nbrs(c: Cell, roads) -> list[Cell]:
    return [n for n in (_add(c, d) for d in ORTHO) if n in roads]


def connected_to_th(roads, th: Footprint) -> bool:
    """Same test as roads_first._check_pattern, as a predicate."""
    if not roads:
        return False
    border = th.border_cells()
    seen = {c for c in roads if c in border}
    stack = list(seen)
    while stack:
        c = stack.pop()
        for n in road_nbrs(c, roads):
            if n not in seen:
                seen.add(n)
                stack.append(n)
    return len(seen) == len(roads)


def valid(roads, th: Footprint, region) -> bool:
    return (bool(roads) and roads <= region and not (roads & th.cells())
            and connected_to_th(roads, th))


def _finish(roads, th, region, old) -> frozenset | None:
    roads = frozenset(roads)
    if roads == old or not valid(roads, th, region):
        return None
    return roads


def leaves(roads, th: Footprint) -> list[Cell]:
    """Cells with one road neighbour that do not touch the TH."""
    border = th.border_cells()
    return sorted(c for c in roads if len(road_nbrs(c, roads)) == 1 and c not in border)


def arm(roads, th: Footprint, leaf: Cell) -> list[Cell]:
    """Cells from `leaf` back to (excluding) the first junction (>= 3 road
    neighbours); a cell touching the TH ends the arm and is included."""
    border = th.border_cells()
    out, prev, cur = [leaf], None, leaf
    while cur not in border:
        nxt = [n for n in road_nbrs(cur, roads) if n != prev]
        if len(nxt) != 1:
            break
        n = nxt[0]
        if len(road_nbrs(n, roads)) >= 3:
            break
        out.append(n)
        prev, cur = cur, n
    return out


def _straight_dir(cells: list[Cell]) -> Cell | None:
    """Unit direction from cells[-1] (root end) to cells[0] (leaf) if the cells
    are one straight run, else None. A single cell has no direction."""
    if len(cells) < 2:
        return None
    (x0, y0), (x1, y1) = cells[0], cells[-1]
    if x0 == x1:
        d = (0, 1 if y0 > y1 else -1)
    elif y0 == y1:
        d = (1 if x0 > x1 else -1, 0)
    else:
        return None
    if any(cells[i] != _add(cells[-1], d, len(cells) - 1 - i) for i in range(len(cells))):
        return None
    return d


def _grow(start: Cell, d: Cell, n: int, roads, th: Footprint, region) -> list[Cell]:
    """Up to n new cells from `start` (a road cell) in direction d. Stops at the
    region edge, the TH, an existing road, or a cell that would touch any road
    other than its predecessor."""
    thc = th.cells()
    out, prev = [], start
    taken = set(roads)
    for _ in range(n):
        c = _add(prev, d)
        if c not in region or c in thc or c in taken:
            break
        if any(m in taken and m != prev for m in (_add(c, e) for e in ORTHO)):
            break
        out.append(c)
        taken.add(c)
        prev = c
    return out


# ------------------------------------------------------------------ operators

def extend(roads, th, region, rng: random.Random, max_len: int = 6):
    lv = leaves(roads, th)
    if not lv:
        return None
    leaf = rng.choice(lv)
    (p,) = road_nbrs(leaf, roads)
    d = (leaf[0] - p[0], leaf[1] - p[1])
    new = _grow(leaf, d, rng.randint(1, max_len), roads, th, region)
    return _finish(set(roads) | set(new), th, region, roads) if new else None


def shorten(roads, th, region, rng: random.Random, max_len: int = 6):
    lv = leaves(roads, th)
    if not lv:
        return None
    a = arm(roads, th, rng.choice(lv))
    border = th.border_cells()
    cut = [c for c in a if c not in border][:rng.randint(1, max_len)]
    if not cut or len(cut) >= len(roads):
        return None
    return _finish(set(roads) - set(cut), th, region, roads)


def remove(roads, th, region, rng: random.Random):
    lv = leaves(roads, th)
    if not lv:
        return None
    a = arm(roads, th, rng.choice(lv))
    if len(a) >= len(roads):
        return None
    return _finish(set(roads) - set(a), th, region, roads)


def shift(roads, th, region, rng: random.Random, max_shift: int = 3):
    """Translate a straight arm by s cells perpendicular to it; its root must
    again sit next to the rest of the network (i.e. on the trunk)."""
    lv = leaves(roads, th)
    rng.shuffle(lv)
    for leaf in lv[:8]:
        a = arm(roads, th, leaf)
        d = _straight_dir(a)
        if d is None:
            continue
        rest = set(roads) - set(a)
        perp = (d[1], d[0])
        shifts = [s for s in range(-max_shift, max_shift + 1) if s]
        rng.shuffle(shifts)
        for s in shifts:
            moved = [_add(c, perp, s) for c in a]
            if any(c in rest for c in moved):
                continue
            if not road_nbrs(moved[-1], rest) and moved[-1] not in th.border_cells():
                continue
            out = _finish(rest | set(moved), th, region, roads)
            if out is not None:
                return out
    return None


def add(roads, th, region, rng: random.Random, max_len: int = 10):
    cells = sorted(roads)
    for _ in range(20):
        c = rng.choice(cells)
        d = rng.choice(ORTHO)
        new = _grow(c, d, rng.randint(2, max_len), roads, th, region)
        if new:
            out = _finish(set(roads) | set(new), th, region, roads)
            if out is not None:
                return out
    return None


def th_sides(th: Footprint) -> dict[str, tuple[list[Cell], Cell]]:
    """side -> (the cells just outside it, outward direction)."""
    x, y, w, l = th.x, th.y, th.width, th.length
    return {"N": ([(i, y - 1) for i in range(x, x + w)], (0, -1)),
            "S": ([(i, y + l) for i in range(x, x + w)], (0, 1)),
            "W": ([(x - 1, j) for j in range(y, y + l)], (-1, 0)),
            "E": ([(x + w, j) for j in range(y, y + l)], (1, 0))}


def free_sides(roads, th: Footprint) -> list[str]:
    return [s for s, (cells, _) in th_sides(th).items() if not any(c in roads for c in cells)]


def spoke(roads, th, region, rng: random.Random, max_len: int = 12, min_len: int = 3):
    """A new straight arm off a TH side that no road touches yet (a second
    trunk; later `add` moves can branch off it)."""
    sides = free_sides(roads, th)
    rng.shuffle(sides)
    thc = th.cells()
    for s in sides:
        cells, d = th_sides(th)[s]
        cells = [c for c in cells if c in region]
        rng.shuffle(cells)
        for c0 in cells:
            if any(m in roads for m in (_add(c0, e) for e in ORTHO)):
                continue
            new = [c0] + _grow(c0, d, rng.randint(min_len, max_len) - 1,
                               set(roads) | {c0}, th, region)
            if c0 in thc or len(new) < min_len:
                continue
            out = _finish(set(roads) | set(new), th, region, roads)
            if out is not None:
                return out
    return None


def merge(roads, th, region, rng: random.Random, max_gap: int = 8):
    """Two straight parallel arms (same direction) whose roots lie on one
    trunk line, 2..max_gap apart: replace both by one arm at the midpoint, as
    long as the longer of the two (grown until an obstacle)."""
    arms = []
    for leaf in leaves(roads, th):
        a = arm(roads, th, leaf)
        d = _straight_dir(a)
        if d is not None:
            arms.append((a, d))
    pairs = []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            (a, d), (b, e) = arms[i], arms[j]
            if d != e:
                continue
            ra, rb = a[-1], b[-1]
            along = (ra[0] - rb[0]) * d[0] + (ra[1] - rb[1]) * d[1]
            gap = abs((ra[0] - rb[0]) * d[1]) + abs((ra[1] - rb[1]) * d[0])
            if along == 0 and 2 <= gap <= max_gap:
                pairs.append((a, b, d))
    rng.shuffle(pairs)
    for a, b, d in pairs:
        rest = set(roads) - set(a) - set(b)
        ra, rb = a[-1], b[-1]
        mid = ((ra[0] + rb[0]) // 2, (ra[1] + rb[1]) // 2)
        base = _add(mid, d, -1)
        if base not in rest:
            continue
        new = _grow(base, d, max(len(a), len(b)), rest, th, region)
        if not new:
            continue
        out = _finish(rest | set(new), th, region, roads)
        if out is not None:
            return out
    return None


def prune(roads, th, region, used):
    """The network the objective actually kept (a layout's road cells)."""
    if used is None:
        return None
    return _finish(frozenset(used), th, region, roads)


OPS = {"extend": extend, "shorten": shorten, "remove": remove, "shift": shift,
       "add": add, "spoke": spoke, "merge": merge}


def mutate(roads, th, region, rng: random.Random, *, ops=None, n_ops: int = 1,
           tries: int = 30):
    """Apply `n_ops` random operators in sequence. Returns (roads, [names]) or
    None if no valid change was found in `tries` attempts."""
    names = list(ops or OPS)
    for _ in range(tries):
        cur, done = frozenset(roads), []
        for _ in range(n_ops):
            name = rng.choice(names)
            nxt = OPS[name](cur, th, region, rng)
            if nxt is None:
                break
            cur, done = nxt, done + [name]
        if done and cur != roads:
            return cur, done
    return None
