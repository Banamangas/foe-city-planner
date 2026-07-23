# Richer-skeleton feasibility diagnostic — design

_2026-07-21. Track: R&D (decide whether richer skeleton families can beat 102). Status: spec, not yet planned._

## 1. Motivation

Two levers this session (placement objective, exact router) both came back near-null and both
pointed the same way: the darkzig floor of **102 roads** is limited by the **placement/skeleton**,
not by the routing objective or the greedy router. The remaining lever with real headroom is
**richer skeleton families** — escaping the comb family.

But the naive version is already closed. `lessons.md` records that lane, stub, and the cap=24
hybrid families were all tried and **lost** to comb (best non-comb = 106): their long straight
corridors are *structurally* closer to the expert's real city yet **harder for CP-SAT to
decide** (e.g. lane probes are 6/6 UNKNOWN at k=115 where comb resolves fast). Comb wins at 102
because it is *decidable*, not because it is structurally optimal. So the real problem is a
tension: generate skeletons that are both structurally better **and** decidable.

Before committing to a big build (a learned skeleton generator), we need to know **why** richer
families lose at low k. Those sub-102 lane/hybrid skeletons were only ever judged at a 30 s
probe budget at equal wall-clock. Nobody has isolated whether they are:

- **UNSAT** — genuinely infeasible; the structure cannot pack that tight → a **feasibility
  wall**, and no generator saves it; or
- **UNKNOWN** — feasible but CP-SAT can't *prove* it in the budget → a **decidability wall**,
  which a better encoding / solver / learned warm-start could crack.

This is exactly the question `scripts/kwalk_autopsy.py` was built to answer for the comb
frontier (Track C-bis Stage 1.5). This diagnostic reuses that pattern for the richer families.

## 2. The question

For **lane** and **hybrid (cap=24)** skeletons at k-levels below comb's 102 floor, probed with a
**large** per-probe budget (not the 30 s the prior runs used), and measuring the **achieved
`route()` count** (not just SAT/UNSAT):

- Does any lane/hybrid skeleton resolve **SAT with achieved < 102**?
- Or are they **UNSAT** (feasibility wall) / **UNKNOWN** (decidability wall)?

The metric that matters is the **achieved road count**, not k: `route()` computes the network
from the consumer placement, and empirically achieved < k, so a SAT at k ≤ ~104 whose placement
routes below 102 is the win condition — and a re-verified new all-time best.

## 3. Method

A variant of `scripts/kwalk_autopsy.py`, reusing `generate_patterns` (comb),
`generate_lane_patterns` (lane; hybrid = lane with `max_lane_len=24`), `probe`, and `validate`:

- **Families:** `lane`, `hybrid` (cap=24) — the structurally-promising ones — plus `comb` as a
  **control** (expected to be UNSAT/UNKNOWN below its own floor, calibrating the lane/hybrid
  reads).
- **k-levels:** spanning below and around comb's 102 floor — e.g. `k ∈ {96, 100, 104}`.
- **Sampling:** full-TH (`th_mode="full"`, 2162 TH positions on darkzig), a modest sample per
  (family, k) — e.g. ~12–15 patterns — shuffled with a fixed seed for reproducibility.
- **Budget:** large per probe — e.g. **300 s**, multi-worker (`probe_workers` 8–12), matching
  the autopsy's "give CP-SAT its best chance to resolve UNKNOWN" intent.
- **Achieved count:** for every **SAT**, run `validate(layout, pattern, positions)` to get the
  achieved `route()` count and whether it beats 102; verify legality
  (`rotated_buildings == 0`, `is_valid`) on any sub-102 result.
- **Output:** per (family, k) tally of SAT / UNSAT / UNKNOWN, the achieved counts of all SATs,
  and the min achieved per family.

## 4. Pre-committed verdict

- **Any lane/hybrid SAT achieves < 102** → **richer family breaks the floor.** Decidability was
  the fixable barrier; pursue the next track (learned generator, or a decidability-improving
  encoding). Independently re-verify the sub-102 layout — it is a new all-time best.
- **No SAT below 102, and the sub-102 probes are decided** (UNSAT-dominated; any SATs land at
  **≥ 102**, like the cap=24 hybrid's 106) → **structural feasibility wall.** These families are
  feasible only at counts at or above comb's, not below; this route to <102 is closed. Redirect
  away from richer parametric families (toward, e.g., a fundamentally different placement search).
- **Persistent UNKNOWN at 300 s** (no SAT below 102, and the sub-102 probes are largely UNKNOWN
  rather than resolved) → **hard decidability wall.** CP-SAT cannot decide these structures even
  with budget; a richer family is only viable with a different solver/encoding (or the
  exact-placement inner model is intractable for lanes). This is the same "INCONCLUSIVE → harder
  frontier" branch the comb autopsy defined.

Whichever fires, the diagnostic has cheaply chosen the next track (or closed it) before any
generator is built.

## 5. Non-goals (scope fence)

- **No skeleton generator is built.** This is a read-only diagnostic; it produces a verdict, not
  a new family or a learned policy.
- **Comb is a control, not the target** — we already know comb's floor is 102.
- **The exhaustive option is out of scope.** Enumerating all ~55k full-TH patterns per k-level
  (the cost of which was estimated: ~1 day/k-level on ~16 cores, removing the portfolio-luck
  problem) is a *thorough* alternative, but this diagnostic deliberately samples to get the
  decidability-vs-feasibility signal in hours. If the sampled diagnostic is promising but
  ambiguous, an exhaustive frontier sweep is a follow-up, not part of this spec.
- **Expert-derived / RL-generated skeletons** (the other two directions raised in brainstorming)
  are separate tracks, gated on this diagnostic's verdict.

## 6. Risks / open questions

- **Sampling can miss a rare SAT.** A modest sample at big budget is a *screen*: it detects
  whether SATs *exist* and reads the UNSAT/UNKNOWN mix, but "no SAT found" is evidence, not proof
  (unlike an exhaustive sweep). The verdict language reflects this — "all UNSAT in the sample" is
  read as a feasibility wall only when the control and the mix support it, and an exhaustive
  follow-up is the escalation if the screen is ambiguous.
- **Cost is data-dependent.** UNSAT probes are fast (~2 s), only UNKNOWN pins at the full budget.
  A feasibility-wall result is cheap (mostly fast UNSAT); a decidability-wall result is the
  expensive case (many probes burn the full 300 s). Expect a few hours; longer if the frontier is
  UNKNOWN-heavy.
- **We only test lane + hybrid.** A family we don't generate could in principle behave
  differently, but lane/hybrid are the structurally-promising ones (closest to the expert's
  double-loaded topology) and the ones the prior runs flagged; they are the right first read.
- **Legality.** Any sub-102 SAT must pass the `rotated_buildings`/`is_valid` guard before being
  claimed as a new best (the project's standing rule after the retracted-127 incident).

## 7. Deliverables

- A diagnostic script (a `kwalk_autopsy`-style variant, e.g. `scripts/exp_richer_skeleton_probe.py`)
  that generates the family/k grid, probes at the big budget, records SAT/UNSAT/UNKNOWN +
  achieved counts, and prints the per-family tally and the pre-committed verdict.
- A `tasks/lessons.md` entry with the tally, the achieved counts, the gate arithmetic, and the
  verdict (break-the-floor / feasibility-wall / decidability-wall), in the voice of the existing
  autopsy and "TESTED … closed" entries.
