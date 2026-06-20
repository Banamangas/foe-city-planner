# FoE City Layout Optimizer — Short-Side-Facing Attachment Design

**Date:** 2026-06-20
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** the road-minimizing multi-start packer (merged).

## 1. Purpose

Lower the `layout` engine's road count toward the Σ(min-side)/2 estimate by attaching road-needing
buildings **short-side-to-road**, so each building presents its shorter edge (fewer cells) to the road
network.

## 2. Motivation (measured)

On DarkZig the road-minimizing packer reaches 169 roads (estimate 114). Analysis of that layout:
- Total building-to-road adjacencies = **302** vs the ideal **228** (= Σ min-side) — because **17 of
  34** non-square road-needing buildings face the road on their **long** side, consuming more road
  frontage than necessary.
- Road-cell sharing averages 1.79 buildings/cell (ideal 2.0).

This design targets the orientation half of that gap (302 → toward 228). The double-row pairing half
(1.79 → 2.0) is deferred (lever B).

## 3. Scope

- Add `first_fit_adjacent_short(grid, w, l, targets)` to `foeopt/packing.py`.
- Use it (with a fallback to `first_fit_adjacent`) for the road-needing attachment in
  `build_candidate` (`foeopt/packer.py`).
- No change to fillers, the gap-fill pass, routing, `repack` scoring, `PackConfig`, or the CLI.
- `improve`/`roads`/`view`/`anneal` untouched.

## 4. Geometry — the "short side"

A building `w × l` placed at `(x, y)` occupies `x..x+w-1` × `y..y+l-1`. Its **short-side border** is the
ring cells along the edges perpendicular to its **long** axis (the edges whose length is the smaller
dimension):

- if `w < l` (taller than wide): top + bottom edges →
  `{(x+i, y-1) for i in range(w)} ∪ {(x+i, y+l) for i in range(w)}`
- if `l < w` (wider than tall): left + right edges →
  `{(x-1, y+j) for j in range(l)} ∪ {(x+w, y+j) for j in range(l)}`
- if `w == l` (square): there is no preferred side → no short-side border.

## 5. Function

`first_fit_adjacent_short(grid, w, l, targets) -> tuple[int,int] | None`:
- For a **square** (`w == l`) return `None` immediately (the caller falls back to the plain variant).
- Otherwise scan positions in the same bottom-left order as `first_fit_adjacent` (`for y in
  range(height): for x in range(width)`) and return the first `(x, y)` where `grid.fits(x, y, w, l)`
  **and** the building's short-side border (per §4) intersects `targets`.
- Return `None` if no such position exists.

## 6. Use in `build_candidate`

In the road-needing attachment step, replace:
```python
        p = first_fit_adjacent(grid, bw, bl, road)
```
with:
```python
        p = (first_fit_adjacent_short(grid, bw, bl, road)
             or first_fit_adjacent(grid, bw, bl, road))
```
So attachment prefers a short-side-to-road spot and **falls back** to any touching spot (squares, or
when no short-side spot exists). Everything else in `build_candidate` is unchanged.

## 7. Invariants preserved

- **Placement not regressed:** the fallback places a building wherever it could before; the multi-start
  `(len(unplaced), len(roads))` scoring still drives to 0 unplaced (verified: DarkZig stays 224/224).
- **Determinism:** deterministic bottom-left scan; `build_candidate` stays deterministic given its
  `PackConfig`.
- **Validity / conservation / never-invalid:** unchanged — same placement machinery, only the
  preferred position differs.

## 8. Testing (TDD)

- **`first_fit_adjacent_short` unit tests:** a `2×4` building returns a spot with its short (2-wide)
  edge on a road target when one exists; a long-side-only target yields `None`; a square returns
  `None`; no fit → `None`.
- **`build_candidate` / determinism / conservation / real-city tests** stay green; DarkZig stays
  0 unplaced.
- **Recorded DarkZig measurement** (not a fast suite test): `repack` 30s roads (expect **< 169**),
  0 unplaced, valid; also report building-to-road adjacencies (expect closer to 228).

## 9. Risk / limitations

- Heuristic: the gain is empirical. If a short-side bias hurts a trial's packing, the multi-start
  discards it (scoring prefers fewer unplaced, then roads), so the result is never worse than today —
  worst case it simply doesn't improve, which the recorded measurement will show.
- Captures only the orientation half of the 169 → 114 gap; reaching ~114 also needs double-row pairing
  (deferred).
