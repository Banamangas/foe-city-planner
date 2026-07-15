# Track C-bis: Learned Acceleration of the Roads-First k-Walk

**Date**: 2026-07-14
**Status**: **ARCHIVED (2026-07-15)** — experimentally closed. Stage 0 (data engine) and Stage 1
(feasibility CNN + scheduler) were built and gated; Stage 1 scheduling gave **zero** end-to-end
k-walk benefit despite a strong held-out AUC (0.999), and the Stage 1.5 UNKNOWN autopsy found **no
feasible-but-hard SAT** at the frontier (0 SAT / 4 UNSAT / 4 UNKNOWN), so Stage 2 (CP-SAT warm-start)
was not justified. Conclusion: the darkzig frontier (~k=110, ~102–106 validated roads) is a
**pattern-family limit**, not an ordering or SAT-proving-speed limit — ML is not the lever here. The
remaining lever to go lower is skeleton **topology** (a separate non-ML track), or more compute.
Assets kept on main: the Stage-0 corpus engine (`foeopt/corpus.py`, opt-in `--corpus`), the feasibility
CNN (`rl/kwalk_*`), and the opt-in scorer hook. Full write-up: `tasks/lessons.md` (2026-07-15
entries). The staged design below is preserved as the record of the bet and why it was gated.

## Goal

Use the roads-first CP-SAT k-walk as an **optimal-labeled data engine**, and learn a
model that lets the walk go **deeper** (below the current 106 roads on darkzig) or
**scale** to the larger FR cities within the same time budget — by attacking the walk's
real bottleneck, the UNKNOWN probes. This reframes the shelved RL bet (Track C, M2–M4)
under conditions that neutralize its three documented failure modes, rather than reviving
the original place-then-route policy.

## Why the conditions are different (the premise)

The M2–M4 RL policy had to jointly design roads, place buildings, and preserve
Townhall-connectivity, judged on a global road count. Its failures (`tasks/lessons.md`,
Track C):

| Old RL killer | Roads-first neutralization |
|---|---|
| `unroutable` — a placement severed free space from the TH frontier (0% success at darkzig fill; the reason `foeopt/reach.py`'s C1 mask existed) | The skeleton is **fixed and pre-connected to the TH** before any building is placed. There is no connectivity to break. |
| Road objective mismatch — `mean_roads ≈ 3× target`; couldn't learn to leave channels | `k` is **fixed externally**. The sub-problem is placement *feasibility against a given skeleton* — no road-count objective to get wrong. |
| Roads unobservable — policy never saw roads until the terminal `route()` (the unbuilt C2) | The skeleton is the **fixed input**, fully observed every step. C2 (a road channel) becomes trivial. |

So the learnable sub-problem collapses from a globally-coupled NP-hard co-design to:
*"pack the road-needing buildings so each touches this fixed, pre-connected skeleton."*
Fully observable, densely labelable, no connectivity reasoning.

The k-walk already generates the data: the darkzig 6h run made **2189 probes**
(230 SAT / 1315 UNSAT / 642 UNKNOWN); each SAT probe carries CP-SAT's placement. That is
the optimal expert on the exact sub-problem, at scale, that the earlier BC lacked (its only
teacher was the repack packer, capping quality at ~169 and causing the 45%→6% collapse).

## Reality check that governs the whole track

Roads-first **already won its gate** (106 ≤ 148, beating the local floor of 158) with pure
CP-SAT. This track is an **accelerator, not a fix**: CP-SAT stays the certificate authority
(the final SAT/UNSAT decider). Learned components only earn their place if they clear a gate
defined against 106. Per the project's measure-first discipline, each stage has a
pre-committed kill criterion.

## Decisions (from the design discussion)

| Decision | Choice |
|----------|--------|
| Framing | Accelerate the k-walk; do NOT replace CP-SAT or revive the end-to-end road policy |
| First bet | **Supervised feasibility classifier** (not RL) — lowest risk, sidesteps the sequential-greedy trap |
| Stage 1 model | **Small CNN** over the `[C,H,W]` grid (reuses `rl/encode.py` + a road channel) |
| Corpus scope | **darkzig + one FR city** (train), a second FR city held out for generalization |
| Escalation | Learned placement proposer as **CP-SAT warm-start (solution hints)** — only if Stage 1 passes AND the Stage 1.5 autopsy proves the frontier is feasible-but-hard |
| Stage 2 gating | **Conditional on the Stage 1.5 UNKNOWN autopsy** — do not build Stage 2 until a one-time CPU experiment proves ≥1 frontier UNKNOWN is actually SAT |
| Ground truth | CP-SAT remains the decider; learned models only schedule/prune/hint |
| Data source | Instrument the existing k-walk; corpus is a zero-solve-cost side effect of normal runs |
| Gate anchor | Everything measured against **106 on darkzig at equal wall-clock** |

## Architecture

### Stage 0 — Data engine (foundational, cheap, reusable)

Extend the probe logger in `foeopt/roads_first.py` (currently logs `{k, params, status}`
via `log(...)`) to persist a **labeled instance corpus**. For each probe record:

- `city` id, `k`, pattern `params` (the skeleton is deterministically reconstructable from
  `params` via the pattern generator — no need to store cell lists),
- the building multiset actually placed against it (entity ids + `(w, l)` + road level),
- `status ∈ {SAT, UNSAT, UNKNOWN, ROUTE_FAIL, INVALID, SAT_FILLER_FAIL, SAT_ROTATED, PREFILTERED}`,
- the CP-SAT solve time (already have per-probe timing),
- **for SAT: the placement `pos`** (building → `(x, y)`), which `probe()` already returns
  but the log currently drops.

Output: an append-only corpus (JSONL alongside `probes.jsonl`, or `.npz` shards). Generated
by re-running the **darkzig + one FR-city** k-walks (the FR runs already exist under
`output/roads-first/`); no new solve cost beyond re-running what we already run. A **second
FR city is held out entirely** from the corpus, reserved for the Stage 3 generalization gate.

**Stage-0 deliverable:** a corpus of ≥ ~10k labeled instances spanning darkzig + one FR
city, with SAT placements included, and a loader that reconstructs `(region, skeleton,
buildings)` from a record. This artifact is valuable even if every later stage is killed.

### Representation

Reuse `rl/encode.py::encode_obs` (`[C,H,W]`: region mask, occupancy, w/l planes, needs-road)
and **add the road-skeleton channel** — the C2 channel, now trivial because roads are the
fixed input. Per-instance features: the fixed skeleton plane, the buildings-to-place as a
size histogram / set encoding, region geometry. This encoder is shared by Stages 1 and 2.

### Stage 1 — Feasibility classifier (primary bet, supervised)

Model: a **small CNN** over the `[C,H,W]` grid (region mask, occupancy, w/l planes,
needs-road, plus the road-skeleton channel), mapping `(region, skeleton, building multiset)
→ P(SAT)`. The building multiset enters as an extra plane / size histogram alongside the
grid. Trained on Stage-0 labels (SAT vs {UNSAT ∪ hopeless}; UNKNOWNs excluded from training
labels, used only as the prediction target at inference). Pure supervised classification —
**no sequential policy**, so the greedy corner-painting failure cannot occur at this stage.
The CNN is chosen over a set-based model because it reuses the existing encoder with the
least new code.

Integration into `RoadsFirstSearch`: use `P(SAT)` to (a) **rank** the many patterns per k so
the most promising are probed first, and (b) **prune / defer** patterns predicted hopeless,
reallocating the time-box toward promising probes and lower k. CP-SAT still decides every
probe it runs — the classifier only changes *which* probes run and *in what order*.

### Stage 1.5 — UNKNOWN autopsy (diagnostic gate; decides whether Stage 2 is built)

Stage 1 (scheduling) and Stage 2 (warm-start) have different ceilings:

- **Stage 1's ceiling = the lowest k with a *fast*-SAT pattern** (provable within
  `--probe-limit`). It only reallocates the fixed budget; if every feasible pattern at the
  frontier k is a *slow* SAT (times out → UNKNOWN), reordering timeouts still gives timeouts.
- **Stage 2's ceiling = the lowest k that is *genuinely feasible at all***. A hint can turn a
  slow/UNKNOWN SAT into a proven SAT, but cannot satisfy a genuinely infeasible instance.

So whether Stage 2 can break 106 depends on *why* the walk stalled at the frontier (k≈116 on
darkzig, 60 UNKNOWNs). Those UNKNOWNs are one of:

1. **Feasible-but-hard** — a SAT hides in them; CP-SAT just couldn't prove it in the budget.
   → Stage 2 is the unlock; Stage 1 alone likely cannot break 106.
2. **Genuinely infeasible under the current pattern family** — no 116-road skeleton of these
   topologies places all buildings. → *Neither* Stage 1 nor Stage 2 helps; the lever is
   better pattern topologies (an orthogonal track), not learning.
3. **Fast-SAT-missed** (sub-case of 1) — a quickly-provable sub-106 pattern exists but was
   never reached due to ordering/budget. → Stage 1 alone suffices; Stage 2 is unnecessary.

**The autopsy** decides between these cheaply, before any model is built for Stage 2: take
the frontier UNKNOWN patterns (the ~60 at k≈116 on darkzig) and re-solve them with a large
per-probe budget (e.g. 10–30 min each) and/or more CP-SAT workers.

- **≥1 flips to SAT** → case 1 (feasible-but-hard): **build Stage 2**; the frontier is
  reachable by warm-start. Record whether any were near-fast (a Stage-1-only win).
- **All flip to UNSAT / stay UNKNOWN under a large budget** → case 2 (infeasible topology):
  **do not build Stage 2**. Conclude that learning cannot break 106 with this pattern family
  and redirect to pattern-topology work. This kills Stage 2 for a few CPU-hours, no GPU.

Cost: a few CPU-hours, no model, no GPU. It converts the "is Stage 2 worth it?" question from
a guess into a measured gate.

### Stage 2 — Placement proposer as CP-SAT warm-start (only if Stage 1 passes AND Stage 1.5 shows case 1)

Model: `(region, skeleton, buildings) → candidate assignment`. Trained by imitation
(`rl/imitate.py`) from the SAT placements in the corpus, optionally refined with RL
(`rl/policy.py` / `rl/ppo.py`) in the reformulated env (below). The proposed assignment is
fed to CP-SAT as **solution hints** (`AddHint`), turning some UNKNOWN probes into fast SAT
proofs — this is where a learned/RL placement properly enters, and where the neutralized
failure modes matter (fully observed skeleton, dense feasibility reward, no routability
break). CP-SAT still owns correctness; a bad hint only wastes time, never certifies a wrong
layout.

**Env reformulation (not a drop-in of M2–M4):** the reward becomes placement feasibility
against a fixed skeleton (dense: fraction placed with a satisfied road-adjacency), the action
mask restricts to road-adjacent anchors for road-needing buildings (the skeleton is known),
and the observation includes the skeleton channel. No `route()` at terminal, no road-count
reward, no articulation mask (connectivity is given).

### Stage 3 — Scale validation (on whatever passed: Stage 1 alone, or Stage 1 + Stage 2)

Re-run the accelerated walk on the **held-out FR city** (bigger, denser, far more UNKNOWNs —
the real payoff for an accelerator, and a true generalization test since it was never in the
corpus). This is where a learned feasibility/warm-start model should matter most, since
CP-SAT's UNKNOWN rate grows with instance size. Runs regardless of whether Stage 2 was built:
if the autopsy killed Stage 2 (case 2), Stage 3 still validates the Stage 1 scheduler here.

## Reuse vs new

| Reuse (paid for) | New / reformulated |
|---|---|
| `rl/encode.py` grid encoder (+ road channel) | Stage-0 corpus logging in `foeopt/roads_first.py` |
| `rl/imitate.py` (BC from SAT placements) | Feasibility classifier + trainer (Stage 1) |
| `rl/gate.py` (go/no-go harness pattern) | `RoadsFirstSearch` probe scheduler hook (rank/prune) |
| `rl/policy.py` / `rl/ppo.py` (Stage 2 RL refine) | Reformulated fixed-skeleton placement env |
| `rl/oracle.py` (small-instance reference) | CP-SAT `AddHint` warm-start path in `probe()` |

## Gates (pre-committed, measured against 106)

All end-to-end gates use the **same darkzig config and seeds** as the 106 run, at **equal
wall-clock**, `rotated_buildings = 0` enforced (per FoE no-rotation memory), and every
reported layout re-validated by `route()` + `is_valid`.

- **G0 (data):** corpus of ≥ ~10k labeled instances across darkzig + one FR city, SAT
  placements included, loader reconstructs instances. Cheap; gate is existence + a sanity
  re-solve of a sample matching the logged status.
- **G1 (Stage 1, go/no-go):** held-out probe classification **ROC-AUC ≥ 0.80** (cheap early
  signal), AND the classifier-guided k-walk reaches **k ≤ 104** (strictly below 106) **or**
  reaches 106 in **≤ 50%** of the compute. Fail → archive the track (keep the corpus + encoder).
- **G1.5 (UNKNOWN autopsy, decides Stage 2):** re-solve the frontier UNKNOWNs (~60 at k≈116
  on darkzig) under a large per-probe budget. **≥1 flips to SAT** → case 1, Stage 2 is
  greenlit. **All UNSAT / still UNKNOWN** → case 2, Stage 2 is **not built**; conclude
  learning cannot break 106 with this pattern family and redirect to pattern topology. CPU
  only, no GPU.
- **G2 (Stage 2; only entered if G1.5 = case 1):** the warm-start converts **≥ 30%** of the
  previously-UNKNOWN probes at the frontier into decided within the same `--probe-limit`, AND
  end-to-end reaches **k < the Stage-1 best**. Fail → keep Stage 1, stop.
- **G3 (Stage 3, scale):** on **≥1 held-out FR city (not in the training corpus)**, the
  accelerated walk reaches a **strictly lower k than the pure-CP-SAT walk** at equal
  wall-clock. Fail → the method helps only the trained cities; ship what passed, do not
  generalize claims.

## Risks and kill conditions

- **Sequential-greedy corner-painting** — mitigated by making Stage 1 supervised (no policy)
  and Stage 2 a *warm-start*, never a replacement; CP-SAT always decides.
- **Distribution shift** — a corpus dominated by one city won't generalize. Mitigated by
  training on darkzig + one FR city and measuring G3 on a **held-out** FR city; if G3 fails,
  add `make_real_like_city` synthetics to the corpus before generalizing claims.
- **The exact solver is already good** — if learned scheduling doesn't beat plain CP-SAT at
  G1, the track dies cheaply; the corpus and encoder remain as paid-for assets.
- **GPU budget** — cap total training at a fixed budget (e.g. 24 GPU-hours across the track,
  matching the old Track C hard-gate framing); exceeding it without clearing a gate is a kill.

## Non-goals

- Replacing CP-SAT as the SAT/UNSAT authority. It stays the ground truth and the final decider.
- Reviving the M2–M4 place-then-route road-designing policy as-is.
- Beating 106 by brute force (more compute); the point is *more* out of the *same* budget.
- Productionizing the learned model into the webapp before it clears G1–G3.

## Resolved decisions (2026-07-15)

1. **Stage 1 model** — small CNN over the `[C,H,W]` grid (reuses `rl/encode.py` with the
   least new code), not a set-based model.
2. **Corpus scope** — darkzig + one FR city for training; a second FR city held out for G3.
3. **Stage 2 is conditional on the Stage 1.5 UNKNOWN autopsy.** Q3 ("is Stage 2 the only path
   below 106?") is decided by measurement, not assumption: Stage 1's ceiling is the lowest
   *fast*-SAT k; Stage 2's ceiling is the lowest *genuinely feasible* k. The autopsy re-solves
   the frontier UNKNOWNs under a large budget — if any is SAT (feasible-but-hard), Stage 2 is
   the unlock and is built; if all are UNSAT (infeasible topology), neither stage helps and
   Stage 2 is killed in favor of pattern-topology work.
