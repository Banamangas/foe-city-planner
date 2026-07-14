# Roads-First Parallel Search — Design

**Date:** 2026-07-07
**Status:** Approved (brainstorm 2026-07-07; user decisions §2)
**Origin:** user request after the 2026-07-07 de-rotated re-run (106 roads, 6h wall-clock): "6h is a long
time to run tests. Is there any way we could speed up this process? Like parallellizing requests?" —
refined against the run's own evidence (90.3% of the 6h budget was UNKNOWN probes pinned at the 30s limit;
200 patterns per k-level probed one-at-a-time on a 16-core box).

## 1. Why this and why now

The de-rotated re-run delivered a verified-legal 106-road win, but the operational profile shows two
compounding wastes:

- **Idle cores.** The box has 16 cores; the search uses 1. The 200 independent patterns at each k-level
  are probed sequentially, and each CP-SAT probe runs `num_search_workers = 1` (a determinism
  pre-commitment from the 2026-07-06 spec §3). At ~9s/probe average and 200 patterns/level, a level takes
  ~30 min — and 12 levels × 30 min ≈ the 6h budget.
- **UNKNOWN-dominated budget.** 642/2189 probes (29%) hit the 30s UNKNOWN limit, consuming 19460.9s =
  5.406h = **90.3% of the 6h budget**. SAT and UNSAT resolve fast (means 4.75s / 0.76s); the cost is
  entirely in probes CP-SAT cannot resolve either way within the limit. The 2026-07-06 operational finding
  already named this as the bottleneck.

Parallelism attacks both at once: running N probes concurrently is a mechanical throughput win (reliable),
and giving each CP-SAT probe M portfolio workers gives it M independent search strategies within the same
`probe_limit` — which flips some UNKNOWNs to SAT/UNSAT (empirical, not guaranteed, but likely helpful at
low-k where the model is loose). The balanced hybrid (both at once) is the user's chosen goal.

The 106 result and the k-walk machinery are unaffected — this is a throughput/quality optimization of the
*search*, not a change to the *problem*. Every saved layout remains independently verifiable-legal because
verification (`route()`, `is_valid`, `rotated_buildings`) is deterministic and runs before save.

## 2. Locked decisions (user, 2026-07-07)

1. **Goal: both, balanced.** Parallelize the 200 independent probes per level (throughput) AND give each
   CP-SAT probe a portfolio of workers (attack UNKNOWN). Not pure throughput, not pure per-probe quality.
2. **Determinism: relax search determinism, keep verification deterministic.** The 2026-07-06 spec §3
   pre-commitment to `num_search_workers = 1, random_seed = 0` is relaxed: `num_search_workers` may be > 1.
   `random_seed = 0` is still set (same starting seed; only portfolio divergence is non-deterministic).
   The search log (`probes.jsonl`) stops being reproducible across runs (same probe may flip SAT/UNKNOWN),
   but every saved `best-k*-a*.json` is still independently verifiable-legal — the science guarantee ("every
   reported road count is a verified-legal achievable count") is preserved. Verification is the source of
   truth, not the search trajectory.
3. **Architecture: Approach 1 — process-pool within each level.** The k-walk stays sequential (each level
   is a synchronization barrier); only the inside of a level is parallelized. Rejected alternatives:
   Approach 2 (speculative next-k) and Approach 3 (global probe queue across all k) — both add
   orchestration complexity and waste compute on levels a sequential walk would skip, for marginal win over
   Approach 1 at 200 patterns/level.
4. **`--patterns` default stays 200.** Measure the parallelism win in isolation first; a separate later
   experiment can test whether more patterns help. No auto-bump.

## 3. Deliverable

One throwaway script, `scripts/exp_roads_first.py` — modified in place, no new file. Run via
`uv run --with ortools` as today. `ortools` stays a throwaway `uv run --with` dependency; `foeopt/` core is
unchanged (per the 2026-07-06 gated-solver-extras policy). The parallelism is pure-Python `multiprocessing`
in the throwaway script — no new dependency.

## 4. Core parallelism model

**Process pool, not threads.** `multiprocessing.Pool(N)` of N worker processes. CP-SAT releases the GIL
during solve, but a process pool is the safe, portable choice — each worker is a fresh process running its
own CP-SAT instance with no shared state. The parent process generates patterns, dispatches, and writes the
log; it never calls CP-SAT itself.

**Core split.** 16 cores total. Default `N = 4` concurrent probes × `M = 4` CP-SAT workers per probe = 16.
This is the balanced split: 4 probes in flight at once (throughput), each CP-SAT probe getting 4 portfolio
workers (attacks the UNKNOWN bottleneck by giving the solver 4 parallel search strategies within the same
`probe_limit`).

**Per-probe CP-SAT config.** `solver.parameters.num_search_workers = M` (was 1), `random_seed = 0`
(unchanged), `max_time_in_seconds = probe_limit` (unchanged). With `M > 1` the solver runs a portfolio of
M parallel search strategies; a probe that all M workers cannot resolve in `probe_limit` stays UNKNOWN
(same status, better-resolved).

**What the parent does per level:**

1. `generate_patterns(...)` deterministically in the parent (same `rng` seed as today) → ordered list of
   patterns. Order is reproducible; only completion order varies.
2. `prefilter` each pattern in the parent (cheap arithmetic, no CP-SAT). Prefiltered proofs (necessary
   conditions only) logged immediately with `status: "PREFILTERED"` and `reason`, as today.
3. Submit surviving patterns to the pool as `(pattern, k)` tasks. Each task runs `probe()` then, on SAT,
   `validate()` in the worker — returning a result dict `(k, params, status, achieved, secs, order,
   layout?)`. The `rotated_buildings` defence-in-depth guard runs in `validate()` before any `OK` return,
   so a layout can only be returned as `OK` if it already passed the orientation check.
4. As results return, the parent logs each row to `probes.jsonl` and saves any improving
   `best-k{k}-a{achieved}.json`/`.html`. Only the parent writes files — race-free.
5. Once all patterns for the level are done (or the deadline fires), compute the level status
   (FEASIBLE / INFEASIBLE / INCONCLUSIVE) per the existing rule and return to the k-walk.

**Worker state.** Workers are stateless: each task carries its own `pattern` + `k`. The read-only
`layout`/`region`/`consumers` are sent to each worker once via a pool initializer (a global in the worker
process), not pickled per task — see §7. No mutable shared state.

## 5. Level barrier, deadline, and probe-limit interaction

**Level as barrier.** Each k-level is a synchronization point: the parent submits all surviving patterns
for that k, waits for all (or deadline), records the level status, then the k-walk decides the next k. The
k-walk logic (`152 → −4 while feasible, bisect the infeasible gap`) is byte-identical to today — only the
inside of a level is parallelized. The walk's audit trail (per-level table, `walk_complete`,
`lowest_feasible_k_probed`, `inconclusive_levels`) is unchanged in structure.

**Deadline handling.** The `--time-box` global wall-clock budget is checked in the parent:
- **Per result return:** when a worker result comes back and `time.monotonic() >= deadline`, the parent
  stops submitting new probes, waits for in-flight ones to finish (each bounded by `probe_limit`), and
  returns the level as INCONCLUSIVE/FEASIBLE per the existing rule.
- **Probe-limit is the per-probe cap** (default 30s, unchanged): a single probe never runs past
  `probe_limit`, so in-flight workers drain within `probe_limit` of a deadline hit — no runaway tail. The
  worst-case overrun past `--time-box` is `probe_limit` (30s), identical to today.

**Probe-limit and probe-workers are independent knobs.** `--probe-limit 30 --probe-workers 4` = 4 workers,
30s wall-cap. No interaction change.

**Pool lifecycle.** One `Pool(N)` created at search start, reused across all k-levels (process reuse —
avoids the ~1s fork + CP-SAT-import overhead per level). Torn down at search end. Workers are stateless.

**Memory.** Each worker holds a copy of the layout (small, ~MB) + its own per-probe CP-SAT model (freed
after each task). 4 concurrent × 4-worker CP-SAT ≈ the same peak memory as a single sequential run with
`num_search_workers = 16` would be — well within a 16-core dev box. No concern.

## 6. Logging, reproducibility, and verification

**Probe log format.** `probes.jsonl` keeps the exact same schema per row (`k`, `params`, `status`,
`achieved`, `secs`, and `reason` for prefiltered). One addition: an `order` field — a monotonic int
assigned by the parent as results return — so the log can be sorted into a stable order for diffing runs
(today the log is append-order, which is sequential and thus already stable; parallel append would
interleave by completion time, which is meaningless to compare). Existing analysis scripts that read
`probes.jsonl` are unaffected (they group by `k`/`status`, not by row order).

**Logging concurrency.** Only the parent writes to `probes.jsonl` (workers return result dicts; parent
serializes writes). No file-locking. `logf.flush()` after each write, as today — a crash or deadline hit
still leaves a complete log up to the last completed probe.

**Saved artifacts (`best-k*-a*.json/.html`).** Written by the parent, only on improving `achieved`. Same
schema as the 106 artifact. Race-free because only the parent writes. The `rotated_buildings`
defence-in-depth guard runs in the worker before a result is returned as `OK` — a layout can only be saved
if it already passed the orientation check. Independent re-verification (the script run on the 106 layout
on 2026-07-07) is unchanged and remains the source of truth.

**Reproducibility stance, made concrete:**
- **Reproducible:** pattern generation order (same `rng` seed), `probe_limit`, `k_start`, `time_box`,
  `patterns` count, the k-walk algorithm, and every saved layout's legality.
- **Non-reproducible:** whether a specific `(k, pattern)` probe returns SAT vs UNKNOWN when
  `--probe-workers > 1` (portfolio divergence), and the `order` field (completion timing varies with core
  scheduling).
- **The science guarantee holds:** every reported road count is a verified-legal achievable count, because
  verification is deterministic and runs before save. Only the search trajectory varies, which is
  acceptable for a feasibility search.

**Selftest.** `--selftest` path is unchanged (single-probe, deterministic, tests the oracle restriction
property). Add one structural assertion: that the parallel path with `--workers 1 --probe-workers 1`
produces the same set of statuses for a tiny fixed pattern set as the sequential path does today — catches
any pool-introduced bug. This is a structural test, not a performance test.

## 7. CLI, defaults, and backward compatibility

**New CLI flags** (additive, all backward-compatible):
- `--workers N` (default 4) — concurrent probe processes. `--workers 1` reproduces today's sequential
  dispatch behavior exactly (one process, no pool overhead).
- `--probe-workers M` (default 4) — CP-SAT `num_search_workers` per probe. `--probe-workers 1` reproduces
  today's portfolio-off behavior exactly.
- Together `--workers 1 --probe-workers 1` = byte-identical to the current sequential run (same
  determinism, same log order modulo the new `order` field).

**Existing flags unchanged:** `--patterns 200`, `--probe-limit 30`, `--time-box 21600`, `--k-start 152`,
`--seed 0`, `--smoke`, `--selftest`, `--dump-patterns`.

**Smoke mode.** `--smoke` keeps its current overrides (20 patterns, 20s limit, 600s box, `k_start = 156`)
and now also forces `--workers 1 --probe-workers 1` — so the 10-min smoke stays a fast, deterministic
sanity check of the de-rotated path, not a parallel-perf test. Parallel perf is measured in a real run.

**Default core split = 4 × 4 = 16.** Matches the 16-core box. A user on an 8-core box would pass
`--workers 2 --probe-workers 4` (or `--workers 4 --probe-workers 2`). Defaults are not auto-detected from
`nproc` — explicit flags keep runs reproducible across machines and avoid a surprise when someone runs on a
bigger box.

**Worker initialization.** The `layout`, `region`, `consumers` are read-only and ~MB; they are sent to
each worker once via a pool initializer (a global in the worker process) rather than pickled per task —
avoids redundant serialization on every one of the 200 patterns. The per-task payload is just
`(pattern, k)`. This is an implementation detail, not a user-facing knob.

**Gated-solver-extras policy.** `ortools` stays a throwaway `uv run --with` dependency. The parallelism is
pure-Python `multiprocessing` in the throwaway script — no new dependency, no change to `foeopt/` core.
The policy is respected.

**Run command, before vs after:**
- Before: `uv run --with ortools python scripts/exp_roads_first.py darkzig.json --probe-limit 30`
- After (default 4 × 4): `uv run --with ortools python scripts/exp_roads_first.py darkzig.json --probe-limit 30`
- Explicit: `... --probe-limit 30 --workers 4 --probe-workers 4`

## 8. What is NOT in scope

- **No change to `foeopt/` core.** Parallelism lives in the throwaway script only.
- **No new dependency.** `multiprocessing` is stdlib; `ortools` stays `uv run --with`.
- **No change to the k-walk algorithm, the gate (≤ 148), the pattern family, or the verification pipeline.**
  Only the inside of a level is parallelized.
- **No `--patterns` default bump.** Measured separately later if the parallelism win is confirmed.
- **No speculative k-level execution.** Approach 2/3 rejected (§2.3).
- **No auto-detection of core count.** Explicit flags only.
- **No change to the smoke mode semantics** beyond forcing single-worker for determinism.

## 9. Acceptance and measurement

The change is a throughput/quality optimization of a throwaway search script. Acceptance is empirical,
measured on the next real run against the 2026-07-07 sequential baseline (106 roads, 2189 probes, 5.988h,
642 UNKNOWN):

- **Throughput (must):** at the default `--workers 4 --probe-workers 4`, the same `--patterns 200
  --probe-limit 30 --time-box 21600` run reaches more k-levels than the baseline's 12 (or the same 12 with
  wall-clock to spare). Expected: ~4x more patterns/hour.
- **UNKNOWN rate (nice-to-have, not a gate):** the fraction of probes returning UNKNOWN is no worse, and
  ideally lower, than the baseline's 29% (642/2189). A portfolio win here is empirical, not guaranteed.
- **Legality (must):** every saved `best-k*-a*.json` independently re-verified as before — 224/224 placed,
  `route()` matches `achieved`, `is_valid` True, `rotated_buildings = 0`, 0 overlaps, 0 out-of-region. This
  is the science guarantee; a failure here blocks the change.
- **Backward compatibility (must):** `--workers 1 --probe-workers 1` reproduces the sequential run's set of
  probe statuses for the same seed (modulo `order`), confirmed by the selftest assertion in §6.

No gate on the road count itself — the 2026-07-06 gate (≤ 148) is already cleared by the 106 result.
Productionization (wiring into `polish`/webapp, tuning for lower k) remains a separate later spec per the
gated-solver-extras policy.

## 10. Self-test

`--selftest` asserts, in addition to today's oracle restriction checks:
1. The parallel dispatch path with `--workers 1 --probe-workers 1` returns the same set of
   `(k, pattern-params, status)` tuples as the sequential path for a tiny fixed pattern set (deterministic
   equivalence at the single-worker corner).
2. With `--workers 2 --probe-workers 1`, the set of statuses is a subset of what the sequential path
   produces (parallelism must not invent new statuses — only completion order and, with portfolio,
   SAT/UNKNOWN flips may differ; at `probe-workers = 1` even those are fixed).

These are structural correctness tests, not performance tests. Performance is measured in the real run
(§9).
