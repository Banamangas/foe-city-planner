"""Routability-preserving placement checks (2026-07-02 spec).

A placement is *safe* iff, after occupying the footprint: (1) every remaining
free component still contains or borders a source cell, and (2) every guarded
border set (placed road-needing buildings + the Townhall) keeps at least one
free cell. Under (1), that surviving border cell is reachable — which is what
route() needs — so a layout grown under this mask can never end unroutable.

`placement_is_safe` is the exact oracle; `ReachChecker` is the per-step
accelerator (built once per placement step, queried per candidate anchor) and
must return identical answers — see tests/test_reach.py's equivalence test.
"""
from __future__ import annotations

from typing import Iterable

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


def _reachable(free: set[Cell] | frozenset[Cell], sources) -> set[Cell]:
    """Free cells reachable from `sources`: seeded at every free cell that is
    a source or orthogonally adjacent to one (sources need not be free)."""
    seeds = [c for c in free
             if c in sources
             or any((c[0] + dx, c[1] + dy) in sources for dx, dy in _ORTHO)]
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        cx, cy = stack.pop()
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in free and n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


def placement_is_safe(free: set[Cell] | frozenset[Cell],
                      footprint_cells: frozenset[Cell],
                      sources: set[Cell] | frozenset[Cell],
                      guarded: Iterable[frozenset[Cell]] = ()) -> bool:
    remaining = set(free) - set(footprint_cells)
    if _reachable(remaining, sources) != remaining:
        return False
    return all(g & remaining for g in guarded)


class ReachChecker:
    """Per-step accelerator: build once for a (free, sources, guarded) state,
    query many candidate footprints. Exact — every answer equals
    placement_is_safe (randomized-equivalence-tested)."""

    def __init__(self, free, sources, guarded: Iterable[frozenset[Cell]] = ()):
        self.free = frozenset(free)
        self.sources = sources
        self.guarded = tuple(frozenset(g) for g in guarded)
        self.reachable = _reachable(self.free, sources)
        self._all_reachable = self.reachable == self.free
        self._seeds = frozenset(
            c for c in self.free
            if c in sources
            or any((c[0] + dx, c[1] + dy) in sources for dx, dy in _ORTHO))

    def is_safe(self, footprint_cells,
                extra_guarded: Iterable[frozenset[Cell]] = ()) -> bool:
        fp = frozenset(footprint_cells)
        guards = self.guarded + tuple(frozenset(g) for g in extra_guarded)
        if not all(any(c in self.free and c not in fp for c in g)
                   for g in guards):
            return False
        if self._all_reachable and not (fp & self._seeds) \
                and self._ring_in_one_band(fp):
            return True
        return placement_is_safe(self.free, fp, self.sources, guards)

    def _ring_in_one_band(self, fp: frozenset[Cell]) -> bool:
        """Fast sufficient check: the ring (free orthogonal neighbours of the
        footprint) lies in one orthogonally-connected component of the free
        band (Chebyshev distance <= 1, so corner cells join the arcs). Then any
        path through the footprint can detour through the band. Empty ring =
        the footprint consumed a whole pocket exactly — nothing to disconnect."""
        ring: set[Cell] = set()
        band: set[Cell] = set()
        for (x, y) in fp:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    c = (x + dx, y + dy)
                    if c in self.free and c not in fp:
                        band.add(c)
                        if abs(dx) + abs(dy) == 1:
                            ring.add(c)
        if not ring:
            return True
        start = next(iter(ring))
        seen = {start}
        stack = [start]
        while stack:
            cx, cy = stack.pop()
            for dx, dy in _ORTHO:
                n = (cx + dx, cy + dy)
                if n in band and n not in seen:
                    seen.add(n)
                    stack.append(n)
        return ring <= seen
