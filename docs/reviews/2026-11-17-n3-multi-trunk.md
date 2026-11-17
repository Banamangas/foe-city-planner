# N3: multi-trunk skeletons (1-4 main roads, one per TH side) -- offline study (2026-11-17)

Branch `feat/n3-multi-trunk` (from `feat/q3-rooted-family`). Script: `scripts/exp_multi_trunk.py`;
drivers `scripts/run_n3_study.sh`, `scripts/run_n3_study2.sh`; rows in `output/n3/run.jsonl`
(per cell) and `output/n3/run_probe.jsonl` (per probe). Every run held the bench lock.

## What was built

`generate_rooted_patterns` has new options. With all of them at their defaults the output is
byte-identical to Q3 (fingerprint taken before and after the change).

- `trunk_dist`: weights for n_trunks = 1..4, each trunk on a distinct TH side. Each trunk keeps
  spoke/flush, T ends and depth-3 sub-branches.
- `min_side_room`: a trunk may use a side only if `side_room` >= this. `side_room` is the number
  of TH-wide layers outward from that side that stay inside the region. Anchors that cannot
  host the smallest count drawable from `trunk_dist` are dropped up front. For 4 trunks only
  central anchors remain.
- `stub_mode="sides"`: at most one stub per TH side, on a TH border cell whose 3 non-TH
  neighbours are free. Such a stub can serve 3 buildings. The old flank pair stays the default;
  left/right flush trunks swallow it.
- `p_spoke`, `p_depth3`, `gap_regimes`: override the module priors. `p_spoke=0, p_depth3=0`
  gives flush-only, depth-2 multi-trunk, i.e. nonuniform with N trunks.
- `RoadsFirstSearch` forwards `rooted_trunks`, `rooted_side_room` and `rooted_stubs`, so a bench
  arm can use them. None of this is in BEST_PRESET.

## Method

- **Matched TH and k.** Per city, two TH positions:
  - `rec`: the record's TH (the upload's TH for the user city);
  - `ctr`: the full-mode anchor with the largest minimum `side_room`, i.e. central.
- **k levels** around each record's skeleton k: darkzig 103/106/110, FR16 80/88, FR17 113/121,
  FR24 230/238/250/265, user 142/145.
- **Pools.** Every arm's pool is built the production way: quality band 3-4, unbanded top-up
  below 10 patterns, prefilter, then the first 8 survivors.
- **Probe.** Each skeleton goes through the production `_run_probe`: position model,
  probe_limit 30 s, objective 30 s, road witness, exact_repair 5 s, 6 procs x 2 CP-SAT workers.
  Every SAT layout was re-checked with `legality.check(..., military="connect")` against the
  uploaded city. All of them were `valid`.
- **Arms.**
  - `nonu`: today's family.
  - `rN`: N trunks, spoke/flush/T/depth-3 priors, `min_side_room=7`, side stubs.
  - `fN` (round 2): N flush-only trunks, depth 2, gaps (10, 18), side stubs, room 7.

## Results: best legal roads after the objective (legal SAT / probed)

All TH positions and k levels pooled per city. The record is the city's all-time best, made
by full 600 s runs with polish, so an offline single-probe study is not expected to reach it.

| city (record) | nonu | r1 | r2 | r3 | r4 | f2 | f3 | f4 |
|---|---|---|---|---|---|---|---|---|
| darkzig (88) | **92** (34/48) | 98 (10/32) | 98 (10/32) | 99 (2/32) | - (0/32) | 100 (1/16) | - (0/16) | not generable |
| FR16 (67) | **70** (13/48) | 78 (2/32) | 73 (3/32) | 79 (1/32) | - (0/32) | 78 (1/16) | - (0/16) | - (0/16) |
| FR17 (103) | **105** (13/48) | - (0/32) | - (0/32) | - (0/32) | - (0/32) | **105** (2/16) | - (0/16) | - (0/16) |
| FR24 (220) | - (0/48) | - (0/64) | - (0/64) | - (0/64) | - (0/64) | | | |
| user (142) | - (0/48) | - (0/32) | - (0/32) | - (0/32) | - (0/16) | - (0/16) | - (0/16) | not generable |

CPU seconds per arm are in `output/n3/run.jsonl` (`secs`). Most rooted and multi-trunk probes are
UNSAT within 0.1-1 s, at presolve, so their cost is low and so is the information.

Matched-TH detail, round-1 cells (rN arms; darkzig k 103/110, FR16 80/88, FR17 113/121): best legal roads, with the legal SAT count in brackets.

| city | TH | nonu | r1 | r2 | r3 | r4 |
|---|---|---|---|---|---|---|
| darkzig | rec | 93 (9) | 98 (2) | 100 (2) | 99 (2) | - |
| darkzig | ctr | 92 (12) | 98 (8) | 98 (8) | - | - |
| FR16 | rec | 70 (12) | - | - | 79 (1) | - |
| FR16 | ctr | 75 (2) | 78 (2) | **73 (3)** | - | - |
| FR17 | rec / ctr | 105 / 106 | - | - | - | - |

FR16 at the central TH is the one cell where a rooted arm (r2, 73) beats nonuniform at the same
TH (75). It is still worse than nonuniform at the record TH (70).

**No new legal record.** The best layouts were darkzig 92, FR16 70 and FR17 105, against
records of 88, 67 and 103.

## Why: trunks are transport, and 3-4 of them eat the budget

Pool coverage, measured before any solver time: mean grid distance from a free cell to the
nearest road, and the share of free cells more than 6 from any road (no building is that
deep). 40 prefiltered skeletons per arm:

| FR17 k=121, rec TH | nonu | f1 | f2 | f3 | f4 | r1 | r2 | r3 | r4 |
|---|---|---|---|---|---|---|---|---|---|
| mean trunk cells | 38 | 39 | 51 | 77 | 108 | 14 | 35 | 46 | 58 |
| mean dist to road | 4.70 | 5.01 | 5.00 | 5.75 | 6.10 | 6.82 | 6.37 | 6.23 | 6.22 |
| free cells > 6 away | 0.25 | 0.28 | 0.28 | 0.36 | 0.38 | 0.39 | 0.37 | 0.38 | 0.39 |

FR16 and darkzig show the same ordering. Each extra flush trunk runs edge to edge and costs
25-30 cells that carry no branch budget. At these k (the budgets where records live) the
branches that cover the far half of the map are what get cut. The result is presolve UNSAT
(FR17, FR24, user), or a layout 6-9 roads worse (darkzig, FR16). The spoke/depth-3 priors
(rN) lose coverage even at N=1, and Q3's own probe saw the same thing: FR17 121 rooted 1 SAT
of 20, FR24 0 of 40.

## Stubs serving 3 buildings

The motif already exists. The `st3` counter is the number of dead-end road cells touched by 3
distinct buildings in a legal layout. It averages **6.2 per nonuniform layout** on darkzig and
FR17, and 4.4 on FR16. They are branch ends left by pruning, not TH stubs. The side-stub motif
raises it slightly (r3 FR16 8.0, r1 darkzig 7.9), but that never turned into fewer roads.

## Verdict

**Null for this mechanism, at matched TH and k, judged by roads after the objective.**

- 3-4 trunks are now tested, not just untested. r4 produced 0 legal layouts out of 176
  probes across 5 cities. r3 produced 3 out of 192, each 7-9 roads worse than nonu.
- One or two trunks from the flush-only family (f2) tie nonuniform at best (FR17 105). That
  is expected: f2 is nonuniform plus a second trunk.
- FR24 and the user city get nothing from any family at any k tried, nonuniform included.
  Their records come from seeding the upload.
- Caveats:
  - n = 8 probes per cell. CP-SAT timing jitter moves a cell's best by about 1 (FR17 nonu
    105 vs 106 on a repeat).
  - The rN arms used the Q3 priors (spoke 0.5, depth 3 0.5, gaps 6-10 half the time), which
    are not tuned.
  - The room threshold was 7 in every arm. It changes which anchors are eligible, not trunk
    cost.

## Next mechanism

The cost is the edge-to-edge trunk, not the number of TH sides. Ideas, in order:

1. **Budgeted trunks.** Cut each trunk at its outermost useful seed with a hard per-trunk cap
   (for example, side_room / 2), and draw a total trunk share (for example, 30-40% of k) split
   across the N trunks. Pre-flight gate: mean distance to road <= nonuniform's p50 before any
   probe.
2. **Start from the uploads, not from priors.** FR24 and user are reachable only from the
   upload. A mutation search around the seeded layout (another agent's `exp_skeleton_mutation`
   runs this) targets those cities directly. A generator cannot sample a 232-cell network
   exactly.
3. If 1 is null too, stop widening the generator. On darkzig/FR16/FR17 the gap to the record
   is closed by polish (rebase and objective polish), not by skeleton shape. The best offline
   layouts here are 3-4 roads above the records that polish produced.
