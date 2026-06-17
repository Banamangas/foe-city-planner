from __future__ import annotations

from collections import deque

from foeopt.model import Building, Layout

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


class RouteError(Exception):
    pass


def free_cells(layout: Layout) -> set[tuple[int, int]]:
    return set(layout.region.cells) - layout.occupied_cells()


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _bfs_path(
    candidates: set[tuple[int, int]],
    starts: set[tuple[int, int]],
    targets: set[tuple[int, int]],
) -> list[tuple[int, int]] | None:
    """Shortest path through `candidates` from any start to any target.

    Starts are cells already in the tree (or Townhall-root cells). Returns the
    list of cells on the path (including the reached target, excluding starts
    that are already roads). None if unreachable.
    """
    if starts & targets:
        return []  # a target is already connected
    seen = set(starts)
    queue: deque[tuple[int, int]] = deque((s, None) for s in starts)
    parent: dict[tuple[int, int], tuple[int, int] | None] = {s: None for s in starts}
    while queue:
        cell, _ = queue.popleft()
        for dx, dy in _ORTHO:
            n = (cell[0] + dx, cell[1] + dy)
            if n in seen or n not in candidates:
                continue
            seen.add(n)
            parent[n] = cell
            if n in targets:
                path = [n]
                p = parent[n]
                while p is not None and p not in starts:
                    path.append(p)
                    p = parent[p]
                path.reverse()
                return path
            queue.append((n, cell))
    return None


def route(layout: Layout) -> dict[tuple[int, int], int]:
    if layout.townhall is None:
        raise RouteError("layout has no townhall")

    candidates = free_cells(layout)
    th_roots = layout.townhall.footprint.border_cells() & candidates

    # Seed the tree with all Townhall-root cells (brief §1: "tree starts as the
    # set of free cells adjacent to the Townhall footprint").
    tree: set[tuple[int, int]] = set(th_roots)
    levels: dict[tuple[int, int], int] = {cell: 1 for cell in th_roots}

    consumers = sorted(
        layout.road_needing(),
        key=lambda b: min(
            (_manhattan(c, (layout.townhall.footprint.x, layout.townhall.footprint.y))
             for c in b.footprint.border_cells()),
            default=0,
        ),
    )

    for b in consumers:
        targets = b.footprint.border_cells() & candidates
        if not targets:
            raise RouteError(f"no free border cell for {b.name} ({b.entity_id})")
        # already covered by an existing connected tree cell?
        if any(t in tree for t in targets):
            connector = next(t for t in targets if t in tree)
        else:
            starts = tree | th_roots
            path = _bfs_path(candidates, starts, targets)
            if path is None:
                raise RouteError(f"cannot reach {b.name} ({b.entity_id})")
            for cell in path:
                tree.add(cell)
                levels.setdefault(cell, 1)
            connector = path[-1] if path else next(iter(targets & tree))
        levels[connector] = max(levels.get(connector, 1), b.road_level)

    roads = dict(levels)
    return _prune(layout, roads, th_roots)


def _prune(
    layout: Layout,
    roads: dict[tuple[int, int], int],
    th_roots: set[tuple[int, int]],
) -> dict[tuple[int, int], int]:
    """Remove road cells whose removal keeps every consumer satisfied."""
    from foeopt.validate import unsatisfied

    changed = True
    while changed:
        changed = False
        # try removing the highest-coordinate cells first (stable, deterministic)
        for cell in sorted(roads, reverse=True):
            trial = dict(roads)
            del trial[cell]
            probe = Layout(layout.region, layout.buildings, layout.townhall, trial)
            if unsatisfied(probe) == []:
                roads = trial
                changed = True
                break
    return roads
