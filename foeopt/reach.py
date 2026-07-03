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
