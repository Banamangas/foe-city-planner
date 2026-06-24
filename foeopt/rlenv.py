from __future__ import annotations

from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout
from foeopt.report import road_estimate
from foeopt.router import RouteError, route
from foeopt.validate import is_valid

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
                 placement_reward: float = 0.0):
        if layout.townhall is None:
            raise ValueError("PlacementEnv requires a Townhall")
        self.region = layout.region
        self.townhall = layout.townhall
        # Optional dense shaping: a small bonus per successfully placed building.
        # Default 0 (pure sparse terminal). Useful because on a dense city naive
        # rollouts almost always end "unroutable" (a flat -100 gives no gradient);
        # rewarding partial progress lets a policy climb. See docs RL design note.
        self.placement_reward = placement_reward
        movable = [b for b in layout.buildings if not b.is_townhall]
        # default order: largest-area first (hardest to place), then entity_id for
        # determinism. The order is fixed per episode; the agent only picks where.
        self._order = order if order is not None else sorted(
            movable, key=lambda b: (-(b.footprint.width * b.footprint.length), b.entity_id)
        )
        self.target = road_estimate(layout)
        self.reset()

    def reset(self) -> Obs:
        self._placed: list[Building] = [self.townhall]
        self._occ: set[tuple[int, int]] = set(self.townhall.footprint.cells())
        self._ptr = 0
        return self._obs()

    @property
    def current(self) -> Building | None:
        return self._order[self._ptr] if self._ptr < len(self._order) else None

    @property
    def done(self) -> bool:
        return self._ptr >= len(self._order)

    def valid_actions(self) -> list[tuple[int, int]]:
        """All anchor positions where the current building fits without overlap."""
        b = self.current
        if b is None:
            return []
        w, l = b.footprint.width, b.footprint.length
        free = self.region.cells - self._occ
        out = []
        for (x, y) in free:
            if all((x + dx, y + dy) in free for dx in range(w) for dy in range(l)):
                out.append((x, y))
        return sorted(out)

    def step(self, action: tuple[int, int]) -> StepResult:
        b = self.current
        if b is None:
            raise RuntimeError("step() called on a finished episode")
        w, l = b.footprint.width, b.footprint.length
        fp = Footprint(action[0], action[1], w, l)
        cells = fp.cells()
        if not cells <= (self.region.cells - self._occ):
            return StepResult(self._obs(), self.INVALID_PENALTY, True, {"error": "invalid_placement"})
        self._placed.append(replace(b, footprint=fp))
        self._occ |= cells
        self._ptr += 1
        if not self.done:
            return StepResult(self._obs(), self.placement_reward, False, {})
        # all placed → the router scores the layout
        layout = Layout(self.region, self._placed, self.townhall, {})
        try:
            roads = route(layout)
        except RouteError:
            return StepResult(self._obs(), self.INVALID_PENALTY, True, {"error": "unroutable"})
        layout.roads = roads
        if not is_valid(layout):
            return StepResult(self._obs(), self.INVALID_PENALTY, True, {"error": "unsatisfied"})
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
