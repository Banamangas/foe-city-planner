# N7: low-freedom chain composites placed like the TH (2026-11-17)

Branch `feat/n7-chain-anchors` (from `feat/backlog-2026-11`, merged up to `6848aa6`).
Code: `foeopt/roads_first.py`. Tests: `tests/test_chain_anchors.py`. Bench pinned at
`9a211a6` (`/home/born/Github/foe-bench-n7`), output `output/bench/2026-11-17-n7/runs.jsonl`
in that worktree.

## Design

Option `chain_anchors` (int, default 0 = off) on `RoadsFirstSearch`. It needs the
nonuniform family and the position model, and raises otherwise.

- `composite_anchors(region, w, l, limit)`: every top-left position where a w x l block
  fits the region. It stops early once the count passes `limit`.
- `chain_pins(region, consumers, threshold)`: the composites (one-lane, road-needing)
  with fewer than `threshold` anchors. Each comes back as (eid, w, l, anchors, contact).
- `generate_nonuniform_patterns(..., pins=)`: each draw first picks the TH, as before.
  Then `_sample_pins` picks one anchor per pinned composite from the anchors that miss
  the TH and the other pins. If none is left, the draw is skipped. The block is carved
  out of the region the trunk and branches grow in. `_pin_paths` then joins the trunk to
  the composite's contact edge by a shortest path. One BFS distance map is cached per
  (composite, anchor). The path is paid from the k budget. The anchors are stored in
  `Pattern.params["pins"]`.
- `_position_model`: for each pin, the literal of that anchor is forced to 1. If the
  anchor has no literal (no road touches it there), the result is trivially UNSAT
  ("no_anchor").
- Polish phases build their own Patterns without pins, so they may move the composite.
  It stays rigid, and every delivered layout still goes through `validate` and
  `legality.check`.
- Off = `pins=None`: no extra `rng` draws and no new params key. The patterns are
  byte-identical (tested at both generator and `_generate_levels` level).

## Threshold choice: 50

Composite anchor counts on an empty grid, across all 17 cities (only 4 have composites):

| city | composite | size | anchors |
|---|---|---|---|
| agrou | Breezemill + 33 parcels | 71x6 | **14** |
| essay | Breezemill + 3 | 11x6 | 1490 |
| darkzig | 3 chains | 16x3..16x5 | 1776-1850 |
| vini | 2 chains | 12x3, 8x5 | 2366-2516 |

The gap runs from 14 to 1490, so any value from 15 to about 1000 makes the same choice
today. 50 (the user's suggestion) keeps a 3.5x margin over agrou. It stays far below
the point where a random skeleton stops cutting every strip.

## Mechanism check (agrou, single probes, 10 s, 1 thread)

- k=90, no band: preset 6/6 UNSAT `no_anchor` (the Breezemill has no road-adjacent
  anchor); pinned 3 SAT / 1 UNSAT / 2 UNKNOWN.
- k=75, band 3-4: pinned 2 SAT / 1 UNSAT / 5 UNKNOWN.
- In the 600 s bench walk: preset 1000 probes, 998 UNSAT, 0 SAT. anch: 72 probes,
  **27 SAT**, 24 UNKNOWN, 21 UNSAT.

## A/B (600 s, 2 reps; `bench.py report ... --base preset`)

| city | rep | preset | anch:chain_anchors=50 |
|---|---|---|---|
| agrou | 0 | 67 | 67 |
| agrou | 1 | 67 | 67 |
| darkzig | 0 | 90 | 90 |
| darkzig | 1 | 88 | 88 |
| essay | 0 | 62 | **61** |
| essay | 1 | 61 | 61 |

The harness verdict is ADOPT (better 1, worse 0, tie 5). **Honest verdict: NEUTRAL; keep
the option off by default.**
- essay and darkzig pin nothing (their anchor counts are at least 1490, above 50), so
  the anch arm runs the same code path there. The essay 62 -> 61 difference is
  run-to-run noise.
- agrou: every result in both arms is the uploaded city (67, `seed_input`). The SAT
  probes reach validation, `validate_fillers` and `validate_repair` run, and no layout
  comes out. The reason is area. Consumers (1232) + fillers (3019, 189 buildings) + TH
  (42) take 4293 of 4368 cells, so a skeleton city has room for at most 75 roads with
  zero slack, and only 8 free cells at 67. N7 removes the chain blocker. Agrou's
  remaining blocker is filler packing, a separate problem. Candidates are
  `fillers_in_model` with the pins, or rebased polish (which already finds 64 roads for
  the consumers alone; the fillers then fail).

## Records / baselines (all pass `verify_layout_file.py --military connect --reroute`)

- **darkzig 88**: the new legal baseline under the full chain rule. Both arms reach it
  in rep 1. Saved as `docs/records/darkzig-88-roads-full-chain-rule.json`.
- **essay 61**: the first saved essay result. Saved as
  `docs/records/essay-61-roads-first.json`.

## Tests

- `tests/test_chain_anchors.py` (11 tests):
  * anchor enumeration on an irregular strip + body region, plus the early stop;
  * pin selection by threshold;
  * TH exclusion in sampling;
  * carve-out: roads avoid the block, the TH avoids the block, and a road touches the
    contact; the pattern stays connected with k cells;
  * determinism;
  * no-pins identity;
  * the fix in the model (SAT at the pinned anchor; UNSAT when the pin has no contact);
  * off-by-default identity through `_generate_levels`;
  * option validation.
- Full suite: 4 failures, all of which also fail on the base commit `6848aa6`:
  `test_api::test_old_routes_still_served` (no webapp/dist in worktrees), plus FR17/FR24
  k_start expectations (`test_bounds`, `test_overnight_defaults`) that the catalog
  needs_road change `7680652` shifted.
