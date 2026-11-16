# Q3: topology of the legal networks vs the skeleton grammar (2026-11-16)

Analysis half of backlog Q3. No solver runs. Script: `scripts/analyze_network_topology.py`
(about 2 s for all 31 networks: 6 uploads, 22 records, 3 bench layouts); test: `tests/test_network_topology.py`.

## Method

The core measure is the **turn level**. A 0-1 BFS over (cell, axis) states counts the
fewest turns needed to reach each road cell from a seed run, moving only on road cells.
Level = turns + 1. With the seed set to the grammar's trunk (the run on the line flush
to one TH side that touches the TH), the grammar is exactly "level <= 2": trunk = 1,
perpendicular branches = 2, plus the four TH-flank stub cells. A network is in the
grammar if it is a subset of some grammar skeleton. Saved networks are pruned skeletons,
so the subset test is the right one. The test is generous: it ignores the generator's
gap >= 10 rule and lets branches start anywhere on the trunk.

Each extension is scored by the number of road cells it still leaves out of the grammar
(OOG):

| column | extension |
|---|---|
| G | today's grammar: best single flush trunk, level <= 2, plus stubs |
| sp | the trunk may be a **spoke**: the straight run leaving a TH-adjacent cell perpendicular to that side (the TH sits at the trunk's end) |
| of | flush trunk moved to offset d = 0..60 from the TH side, joined by a straight connector |
| 2t | best **two** trunks (flush or spoke, any sides), level <= 2 |
| d3 | best single trunk (flush or spoke), level <= **3** (sub-branches and bent branches) |
| 2t3 | two trunks and level <= 3 |
| T3 | every cell within 2 turns of any TH root |

## Results

Columns: rd roads, sd TH sides with a non-stub root, dep TH-rooted turn depth, seg
straight runs, bnd bends (degree-2 turns), trk/off longest straight run reached with at
most one turn and its offset from the TH edge ("end" = end-on spoke), load consumers per
road cell, 2sd share of road cells used on both sides. There are no holes (loops larger
than a 2x2 square) in any network. The level-2 networks have one 2x2 square (the
two-lane tile). darkzig upload has one loop through the TH.

| network | rd | sd | dep | seg | bnd | trk/off | load | 2sd | G | sp | of | 2t | d3 | **2t3** | T3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| darkzig upload | 250 | 2 | 7 | 13 | 7 | 45/30 | 1.08 | 0.19 | 164 | 164 | 164 | 164 | 42 | 42 | 42 |
| FR16 upload | 92 | 2 | 3 | 5 | 1 | 26/end | 1.98 | 0.92 | 66 | 50 | 14 | 36 | 14 | **0** | 0 |
| FR17 upload | 127 | 2 | 4 | 8 | 3 | 32/11 | 1.96 | 0.91 | 103 | 64 | 55 | 40 | 35 | **11** | 11 |
| FR24 upload | 232 | 2 | 2 | 7 | 2 | 43/5 | 1.97 | 0.95 | 196 | 37 | 159 | **0** | 37 | **0** | 0 |
| user upload (expert) | 142 | 1 | 3 | 4 | 2 | 38/34 | 2.02 | 0.98 | 105 | 68 | **0** | 68 | **0** | **0** | 0 |
| agrou upload | 67 | 1 | 2 | 3 | 1 | 37/0 | 2.04 | 0.95 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fr24-220 seed-input (record) | 220 | 2 | 2 | 7 | 2 | 40/5 | 1.99 | 0.97 | 184 | 37 | 150 | **0** | 37 | **0** | 0 |
| darkzig-88 rebased (record) | 88 | 2 | 3 | 8 | 5 | 24/0 | 1.98 | 0.89 | 43 | 43 | 43 | 32 | 42 | **0** | 0 |
| darkzig-89 pl10 (record) | 89 | 2 | 3 | 8 | 5 | 24/0 | 1.93 | 0.90 | 43 | 43 | 43 | 32 | 43 | **0** | 0 |
| darkzig-99 / -98 / -97-k106 | 99/98/97 | 2/2/1 | 6/2/3 | | | | | | 31/5/1 | | | 27/0/1 | | 25/0/0 | |
| other 16 records + 3 bench | 67-108 | 1 | 2 | 3-8 | 0-5 | 23-45 | 1.94-2.03 | 0.89-0.96 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

The full per-network table, with junction counts, dead-end stubs, histograms and mean
distance to road, comes from `python scripts/analyze_network_topology.py --json out.json`.

## Findings

1. **The records are in the grammar by construction, so their conformity says nothing
   about the grammar.** Every record found by the probe pipeline is a pruned grammar
   skeleton and scores 0. The informative networks are those built outside the generator:
   - the 5 uploads (FR16, FR17, FR24, user, agrou);
   - the rebased-polish networks: the current legal darkzig records 88 and 89, with 43
     cells (49%) out of the grammar;
   - FR24 220, which keeps the upload's topology.
2. **The dense and expert networks are mostly out of the grammar.** Only agrou fits. Out of
   grammar: FR24 196/232 (84%), FR17 103/127 (81%), user 105/142 (74%), FR16 66/92 (72%).
   This is not a loss in efficiency. Their load (1.96-2.04 consumers per road cell) and
   both-sides share (0.91-0.98) match or beat the records (1.92-2.03, 0.89-0.96). Their
   mean distance to road matches too: FR16 5.9 vs 5.0 for its records, FR17 4.8 vs 4.9. The
   difference is the shape: they spread as well as combs and lanes do, but from a different
   root.
3. **Out-of-grammar feature 1: the TH sits at the end of the main road.** FR16, FR17, FR24
   and user all leave the TH through a perpendicular spoke of 24-35 cells. FR16 and FR17
   put the TH in a map corner. The user city is the expert "offset TH": a 34-cell spoke
   ends in a T. That T is a 38-cell trunk parallel to the TH at offset 34, with branches
   hanging off it. The grammar cannot express any of this. Its trunk must touch the TH
   side, and branch seeds start at gap >= 10 from the TH corner, so no branch can be a
   spoke and nothing can hang off one.
4. **Out-of-grammar feature 2: a second root trunk.** FR24 uses a spoke plus a flush run on
   another side, at depth 2. Two trunks alone cover it completely (196 -> 0 OOG). darkzig
   88/89 grow a second network from the TH-flank stub cell (stub -> run -> a 32-cell column),
   which is the "branch from stub" case.
5. **Out-of-grammar feature 3: depth 3.** This means sub-branches, or bent branches that
   reach the same cells. user, FR16 and FR17 need it.
   - FR17 is the only network that needs depth 4, and only for 11 cells.
   - The other features hardly appear: no larger loops, at most 5 bends outside the bad
     darkzig upload, no offset trunk that is not a spoke-plus-T.
6. **How much each extension covers.** Totals are the 470 out-of-grammar cells of the four
   non-trivial non-darkzig uploads (FR16, FR17, FR24, user):

   | extension | OOG left | covered |
   |---|---|---|
   | spoke only | 219 | 53% |
   | two trunks | 144 | 69% |
   | depth 3 (single trunk, flush or spoke) | 86 | 82% |
   | **two trunks + depth 3** | **11** | **98%** |

   Two trunks + depth 3 covers all networks fully except FR17 (11 cells), the original
   250-road darkzig (not a model) and the legacy darkzig-99.

## Recommended extension: TH-rooted trees with up to 2 trunks, depth 3

This is one new family, `generate_rooted_patterns`, next to `generate_nonuniform_patterns`.
It reuses that function's seed, length and growth code (`rng`, gaps, skew, stop at the first
obstacle, exact budget k, dedup, `quality_index_band`).

1. **TH anchor:** `th_anchor_candidates` as today. Corner anchors matter here, because FR16
   and FR17 put the TH in a corner.
2. **Trunks:** `n_trunks` = 2 with probability `p_two` = 0.5, otherwise 1. Each trunk gets a
   side s, distinct for trunk 2, and a kind:
   - `flush` (probability 0.5): today's trunk, with seeds at anchor +/- U[g_lo, g_hi].
   - `spoke` (probability 0.5): pick a root r uniformly among the free TH-adjacent cells of s.
     The four flank stub cells count, which gives the darkzig-88 form. Grow the spoke away
     from the TH to a length l ~ U[2, l_max], where l_max is its free run in the region.
     Seeds go along the spoke at U[1, g_hi], then every +U[g_lo, g_hi].
   - With probability `p_T` = 0.5, also seed **both sides at the spoke's far end** (a T).
     This is the offset-trunk / expert form: user city l = 34, a 38-cell T, combs off
     the arms.
3. **Level-2 branches:** as today. They are perpendicular to their trunk, on one or both
   sides (`both_prob`), with lengths from the expovariate^skew split of the level-2 budget.
4. **Level-3 sub-branches** (probability `p_d3` = 0.5 per pattern): set aside a fraction
   f3 ~ U[0.2, 0.6] of the post-trunk budget. On each level-2 branch longer than g_lo, seed
   sub-branches perpendicular to it at U[1, g_hi], then every +U[g_lo, g_hi]. Split f3
   across them by the same expovariate weights. Level 3 is where the T's arms grow their
   combs.
5. **Gaps:** draw (g_lo, g_hi) per pattern from {(10, 18) as today, (6, 10)}. The expert
   sibling gaps are 7-10 (one 21) on the 3x3-heavy FR cities and 13 on the user city. The 2026-11-11
   "depth-matched gaps refuted" result was measured inside the old grammar, on FR24 with 0
   legal layouts at every gap, so it does not decide this.
6. **Pre-flight before any solver time** (OOD process lesson 1):
   - Check that the family reproduces the FR16, FR24 and user networks as subsets. This
     script's `2t3` test is the oracle.
   - Histogram `quality_index` and mean distance to road over the pool, against the
     in-grammar population.
   - Reject patterns whose mean distance is above that population's 90th percentile.
     Coverage is the binding constraint, and tuning one shape knob can silently clump the
     tree.
7. **Pool mix and judgement:** 50% rooted and 50% nonuniform per level, so that darkzig and
   FR16 do not regress (their records are in-grammar). Judge by **achieved roads after the
   objective** in paired 600 s runs (I1 harness). Gate: FR24 gets a non-seed layout, or
   FR17 drops below 103.

The simpler first step is extension 2 alone: spoke trunks plus two trunks, depth 2. It
covers FR24 exactly, and FR24 is the gate city, so try it first if the full family is too
much at once.

## How this differs from the 21-generator negative result (2026-07-30)

| | OOD v1/v2 (2026-07-30) | this proposal |
|---|---|---|
| shapes | invented: random walks, perturbations, Eden-grown trees | measured: the motifs of 4 working cities |
| structure | clumped trees, coverage 0.040, mean distance 25.6 vs comb 14.9 | a few long straight strokes (seg 4-8, lengths 15-42), the same coverage as records |
| city / k | darkzig only, k = 105/106 | FR24 / FR17 / user, where records cannot follow the uploads |
| probe | **item model**, 300 s, 1 worker, feasibility only, pre-2026-11-11 rules | position model, objective, current legal rules |
| outcome | v2: 0 SAT / 240, of which 207 UNSAT (199 dead at presolve) and 33 UNKNOWN; v1 scatter: 30 SAT, best 103 vs 95 | - |

Most of the old negative still holds: 199 of 240 were proven infeasible at presolve,
whatever the budget, because random trees do not cover the map. Only the 33 UNKNOWNs
(14%) depend on the budget and the item model, and the position model has since
changed what "UNKNOWN" means: "everything UNKNOWN" became a one-minute test. Those
results do not speak to this proposal:

- The study tested darkzig, the one city whose best networks are all in-grammar.
- It tested shapes chosen for being *different*, not shapes taken from working cities.
- It never measured achieved roads after an objective.

The coverage lesson carries over as a hard pre-filter (spec step 6).

## Caveats

- The subset test is generous (no gap constraint, branches anywhere), so "in grammar"
  here means "expressible", not "the generator would draw it".
- The uploads were placed by humans around their own networks. The open question is not
  whether these topologies are legal (they are), but whether CP-SAT can decide them as
  quickly as combs. That needs the follow-up runs.
- n = 5 uploads. The motifs (end-on spoke, T, second trunk) recur in 4 of 5, but the
  probabilities in the spec are priors, not fits.
