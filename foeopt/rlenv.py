from __future__ import annotations

from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout
from foeopt.reach import ReachChecker
from foeopt.report import road_estimate
from foeopt.router import RouteError, route
from foeopt.validate import is_valid, unsatisfied

# Sequential-placement MDP for FoE layout optimization — the foundation for an
# amortized ML/RL solver (the chip-floorplanning formulation). Pure-stdlib: the
# (Task-A-accelerated) router is the simulator. Training code (GNN policy, PPO)
# lives outside the core behind optional deps; this environment is what it drives.
#
# Episode: the Townhall is pre-placed; the agent places the remaining buildings
# one at a time in a fixed order (it chooses WHERE, not WHICH). Roads are computed
# by route() once all buildings are down. Reward is sparse-terminal — fewer roads
# than the Σ(short-side)/2 estimate scores positive — with a hard penalty for an
# unplaceable or unroutable layout. This matches what we proved this session:
# placement is the lever; route() is already near-optimal for a fixed placement.


@dataclass(frozen=True)
class Obs:
    """A raw, framework-agnostic snapshot. A policy encodes this however it likes
    (e.g. grid channels for a CNN/GNN); the environment stays dependency-free."""
    region: frozenset[tuple[int, int]]
    occupied: frozenset[tuple[int, int]]
    current_size: tuple[int, int] | None   # (w, l) of the building to place next
    current_needs_road: bool
    remaining: int                          # buildings left to place (incl. current)


@dataclass
class StepResult:
    obs: Obs
    reward: float
    done: bool
    info: dict


class PlacementEnv:
    """Reset/step environment. `step` takes an (x, y) anchor for the current
    building. Deterministic given the input layout and building order."""

    INVALID_PENALTY = -100.0

    def __init__(self, layout: Layout, *, order: list[Building] | None = None,
                 placement_reward: float = 0.0, potential_shaping: bool = False,
                 cache_valid_actions: bool = False):
        if layout.townhall is None:
            raise ValueError("PlacementEnv requires a Townhall")
        self.region = layout.region
        self.townhall = layout.townhall
        # Optional dense shaping: a small bonus per successfully placed building.
        # Default 0 (pure sparse terminal). Useful because on a dense city naive
        # rollouts almost always end "unroutable" (a flat -100 gives no gradient);
        # rewarding partial progress lets a policy climb. See docs RL design note.
        self.placement_reward = placement_reward
        self.potential_shaping = potential_shaping
        # Optional frontier-optimized valid_actions cache. When set, valid_actions
        # reads an O(1) cached set per (w, l) (maintained by an O(new_cells *
        # footprint) delta on each successful step) and the prior filter reads a
        # delta-maintained frontier set -- eliminating the O(free * footprint)
        # per-step scan that dominates the env loop (see task-7 profiling). Output
        # is bit-identical to the uncached path (see tests/test_rl_throughput.py).
        self._cache_valid_actions = cache_valid_actions
        self._valid_cache: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {}
        self._frontier: set[tuple[int, int]] = set()
        movable = [b for b in layout.buildings if not b.is_townhall]
        # default order: largest-area first (hardest to place), then entity_id for
        # determinism. The order is fixed per episode; the agent only picks where.
        self._order = order if order is not None else sorted(
            movable, key=lambda b: (-(b.footprint.width * b.footprint.length), b.entity_id)
        )
        self._n_road_needing = len([b for b in self._order if b.needs_road])
        self.target = road_estimate(layout)
        self.reset()

    def reset(self) -> Obs:
        self._placed: list[Building] = [self.townhall]
        self._occ: set[tuple[int, int]] = set(self.townhall.footprint.cells())
        self._ptr = 0
        self._reach: ReachChecker | None = None
        self._potential = self._partial_road_estimate()
        if self._cache_valid_actions:
            self._populate_valid_cache()
        return self._obs()

    @property
    def current(self) -> Building | None:
        return self._order[self._ptr] if self._ptr < len(self._order) else None

    @property
    def done(self) -> bool:
        return self._ptr >= len(self._order)

    def valid_actions(self, prior: bool = False, safe: bool = False) -> list[tuple[int, int]]:
        """All anchor positions where the current building fits without overlap.

        With ``prior=True``, restrict to anchors whose footprint is orthogonally
        adjacent to already-placed occupancy (the Townhall + placed buildings).
        This bakes in the grow-tree's contiguity prior — the layout grows as a
        connected cluster rooted at the Townhall, which is what makes it routable
        — and shrinks the action space ~100x. May return [] when no legal anchor
        is adjacent (callers fall back to the full set). Output is sorted for
        determinism.

        With ``safe=True``, further restrict to anchors whose placement is_safe
        per ReachChecker: free space stays connected to the Townhall, and no
        placed road-needing building (nor the candidate itself, if it needs a
        road) loses its last free border cell. Default False leaves every
        existing behavior byte-identical.
        """
        b = self.current
        if b is None:
            return []
        w, l = b.footprint.width, b.footprint.length
        if not self._cache_valid_actions:
            out = self._valid_actions_uncached(w, l, prior)
        else:
            # Cached path: read the per-(w, l) full anchor set + delta-maintained
            # frontier; produce bit-identical output to _valid_actions_uncached.
            full = self._valid_cache[(w, l)]
            if not prior:
                out = list(full)
            else:
                frontier = self._frontier
                out = sorted(a for a in full
                             if any((a[0] + dx, a[1] + dy) in frontier
                                    for dx in range(w) for dy in range(l)))
        return self._filter_safe(out, w, l) if safe else out

    def _filter_safe(self, anchors: list[tuple[int, int]], w: int, l: int) -> list[tuple[int, int]]:
        """Keep anchors whose placement preserves routability: free space stays
        connected to the Townhall and no placed consumer (nor the candidate, if
        it needs a road) loses its last free border cell. Exact via ReachChecker."""
        if self._reach is None:
            guarded = tuple(b.footprint.border_cells()
                            for b in self._placed if b.needs_road)
            free = self.region.cells - self._occ
            self._reach = ReachChecker(free, set(self.townhall.footprint.cells()),
                                       guarded=guarded)
        b = self.current
        out = []
        for (x, y) in anchors:
            fp = Footprint(x, y, w, l).cells()
            extra = (Footprint(x, y, w, l).border_cells(),) if b.needs_road else ()
            if self._reach.is_safe(fp, extra_guarded=extra):
                out.append((x, y))
        return out

    def _valid_actions_uncached(self, w: int, l: int, prior: bool) -> list[tuple[int, int]]:
        free = self.region.cells - self._occ
        frontier = None
        if prior:
            frontier = {
                c for c in free
                for n in ((c[0] - 1, c[1]), (c[0] + 1, c[1]),
                          (c[0], c[1] - 1), (c[0], c[1] + 1))
                if n in self._occ
            }
        out = []
        for (x, y) in free:
            if not all((x + dx, y + dy) in free for dx in range(w) for dy in range(l)):
                continue
            if prior and not any((x + dx, y + dy) in frontier
                                 for dx in range(w) for dy in range(l)):
                continue
            out.append((x, y))
        return sorted(out)

    def _populate_valid_cache(self) -> None:
        """(cache_valid_actions=True) Build the full-anchor cache for every
        distinct (w, l) in self._order and the initial frontier, once per reset."""
        free = self.region.cells - self._occ
        self._frontier = {
            c for c in free
            for n in ((c[0] - 1, c[1]), (c[0] + 1, c[1]),
                      (c[0], c[1] - 1), (c[0], c[1] + 1))
            if n in self._occ
        }
        sizes = {(b.footprint.width, b.footprint.length) for b in self._order}
        for (w, l) in sizes:
            anchors = []
            for (x, y) in free:
                if all((x + dx, y + dy) in free
                       for dx in range(w) for dy in range(l)):
                    anchors.append((x, y))
            anchors.sort()
            self._valid_cache[(w, l)] = tuple(anchors)

    def _delta_update_cache(self, new_cells: frozenset[tuple[int, int]]) -> None:
        """(cache_valid_actions=True) Invalidate only anchors whose footprint
        now overlaps the newly occupied cells, and grow the frontier by the
        free neighbours of those cells. Bit-identical to a fresh repopulate."""
        free = self.region.cells - self._occ
        for (w, l), cached in self._valid_cache.items():
            bad: set[tuple[int, int]] = set()
            for (nx, ny) in new_cells:
                for dw in range(w):
                    for dl in range(l):
                        bad.add((nx - dw, ny - dl))
            if bad:
                self._valid_cache[(w, l)] = tuple(a for a in cached if a not in bad)
        # frontier delta: drop the cells that just became occupied, add free
        # cells that are newly adjacent to occupancy.
        nf = set(self._frontier)
        nf.difference_update(new_cells)
        for (nx, ny) in new_cells:
            for nn in ((nx - 1, ny), (nx + 1, ny), (nx, ny - 1), (nx, ny + 1)):
                if nn in free and nn not in self._occ:
                    nf.add(nn)
        self._frontier = nf

    def step(self, action: tuple[int, int]) -> StepResult:
        b = self.current
        if b is None:
            raise RuntimeError("step() called on a finished episode")
        w, l = b.footprint.width, b.footprint.length
        fp = Footprint(action[0], action[1], w, l)
        cells = fp.cells()
        if not cells <= (self.region.cells - self._occ):
            unplaced = len(self._order) - self._ptr
            total = len(self._order) or 1
            return StepResult(self._obs(), self.INVALID_PENALTY * (unplaced / total),
                              True, {"error": "invalid_placement"})
        self._placed.append(replace(b, footprint=fp))
        self._occ |= cells
        self._ptr += 1
        self._reach = None
        if self._cache_valid_actions:
            self._delta_update_cache(cells)
        if not self.done:
            reward = self.placement_reward
            if self.potential_shaping:
                new_pot = self._partial_road_estimate()
                reward += (new_pot - self._potential)
                self._potential = new_pot
            return StepResult(self._obs(), reward, False, {})
        # all placed → the router scores the layout
        layout = Layout(self.region, self._placed, self.townhall, {})
        try:
            roads = route(layout)
        except RouteError:
            return StepResult(self._obs(), self.INVALID_PENALTY, True,
                              {"error": "unroutable"})
        layout.roads = roads
        if not is_valid(layout):
            n_bad = len(unsatisfied(layout))
            frac = (n_bad / self._n_road_needing) if self._n_road_needing else 1.0
            return StepResult(self._obs(), self.INVALID_PENALTY * frac, True,
                              {"error": "unsatisfied"})
        nroads = len(roads)
        reward = float(self.target - nroads)   # >0 when below the Σ/2 estimate
        return StepResult(self._obs(), reward, True,
                          {"roads": nroads, "target": self.target, "layout": layout})

    def _obs(self) -> Obs:
        b = self.current
        return Obs(
            region=self.region.cells,
            occupied=frozenset(self._occ),
            current_size=(b.footprint.width, b.footprint.length) if b else None,
            current_needs_road=bool(b.needs_road) if b else False,
            remaining=len(self._order) - self._ptr,
        )

    def _partial_road_estimate(self) -> int:
        """road_estimate of the layout formed by the Townhall + buildings placed so far.
        Rises as road-needing buildings are placed -- the potential for shaping."""
        partial = Layout(self.region, self._placed, self.townhall, {})
        return road_estimate(partial)
