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


def _articulation_points(
    roads: dict[tuple[int, int], int], th_border: set[tuple[int, int]]
) -> set[tuple[int, int]]:
    """Road cells whose removal disconnects another road cell from the Townhall.

    Iterative Tarjan over the road graph plus a virtual root connected to the
    road cells bordering the Townhall. The virtual root is never returned.
    """
    if len(roads) <= 1:
        return set()

    root = ("__townhall_root__",)  # sentinel distinct from any (x, y) cell
    adj: dict[object, list[object]] = {}
    for c in roads:
        cx, cy = c
        adj[c] = [(cx + dx, cy + dy) for dx, dy in _ORTHO
                  if (cx + dx, cy + dy) in roads]
    roots = [c for c in roads if c in th_border]
    adj[root] = list(roots)
    for c in roots:
        adj[c] = adj[c] + [root]

    disc: dict[object, int] = {}
    low: dict[object, int] = {}
    art: set[tuple[int, int]] = set()
    timer = 0
    root_children = 0

    stack: list[tuple[object, object, object]] = [(root, None, iter(adj[root]))]
    disc[root] = low[root] = timer
    timer += 1
    while stack:
        node, parent, it = stack[-1]
        advanced = False
        for nb in it:
            if nb == parent:
                continue
            if nb in disc:
                low[node] = min(low[node], disc[nb])
            else:
                if node == root:
                    root_children += 1
                disc[nb] = low[nb] = timer
                timer += 1
                stack.append((nb, node, iter(adj[nb])))
                advanced = True
                break
        if not advanced:
            stack.pop()
            if stack:
                p = stack[-1][0]
                low[p] = min(low[p], low[node])
                if p != root and stack[-1][1] is not None and low[node] >= disc[p]:
                    art.add(p)
    if root_children > 1:
        art.add(root)
    art.discard(root)
    return art


def route(layout: Layout) -> dict[tuple[int, int], int]:
    if layout.townhall is None:
        raise RouteError("layout has no townhall")

    candidates = free_cells(layout)
    th_roots = layout.townhall.footprint.border_cells() & candidates
    if not th_roots:
        raise RouteError("townhall has no free adjacent cell to root the network")

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
            starts = tree
            path = _bfs_path(candidates, starts, targets)
            if path is None:
                raise RouteError(f"cannot reach {b.name} ({b.entity_id})")
            for cell in path:
                tree.add(cell)
                levels.setdefault(cell, 1)
            connector = path[-1]
        levels[connector] = max(levels.get(connector, 1), b.road_level)

    roads = dict(levels)
    return _prune(layout, roads)


def _prune(
    layout: Layout,
    roads: dict[tuple[int, int], int],
) -> dict[tuple[int, int], int]:
    """Remove road cells whose removal keeps every consumer satisfied.

    Building positions are fixed during pruning, so each consumer's border
    cells and the Townhall's border are computed once and reused across all
    trial removals (recomputing them per trial dominated the cost). This is a
    pure speedup: the satisfaction predicate and the deterministic removal
    order (highest-coordinate cell first) are identical to evaluating
    `validate.unsatisfied` on each trial.
    """
    th_border = (
        layout.townhall.footprint.border_cells() if layout.townhall is not None else set()
    )
    # (border cells, required level) per road-needing consumer, computed once.
    consumers = [
        (b.footprint.border_cells(), b.road_level) for b in layout.road_needing()
    ]

    def satisfied(rd: dict[tuple[int, int], int]) -> bool:
        # roads orthogonally connected to the Townhall footprint
        seen = {c for c in rd if c in th_border}
        queue: deque[tuple[int, int]] = deque(seen)
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in _ORTHO:
                n = (cx + dx, cy + dy)
                if n in rd and n not in seen:
                    seen.add(n)
                    queue.append(n)
        for border, level in consumers:
            if not any(c in seen and rd[c] >= level for c in border):
                return False
        return True

    changed = True
    while changed:
        changed = False
        # try removing the highest-coordinate cells first (stable, deterministic)
        for cell in sorted(roads, reverse=True):
            trial = dict(roads)
            del trial[cell]
            if satisfied(trial):
                roads = trial
                changed = True
                break
    return roads
