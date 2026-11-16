"""Single source of truth for the run parameters the web app exposes.

Every entry in OPTION_SPECS mirrors one ``scripts/exp_roads_first.py`` flag
(recorded in ``cli``) and maps 1:1 onto a ``JobManager.submit`` keyword. The
frontend renders the Optimize panel -- basic controls and the Advanced-options
section alike -- straight from this list via ``GET /api/options``, so exposing a
new knob is a one-line edit here.

Defaults are the *webapp* defaults, which intentionally differ from the CLI's
in a few places (workers/probe_workers/concurrent_levels/th_anchors); the
``help`` text says so where it matters.

Deliberately not exposed: ``--corpus`` (writes probe records to a server-side
directory -- a filesystem write path driven by the browser), ``--seed`` (only
affects ``--dump-patterns``; the k-walk itself is hardcoded to Random(0)), and
``--selftest``/``--dump-patterns``, which are not searches. ``--smoke`` is not a
parameter but a preset, served as SMOKE_PRESET below.
"""
from __future__ import annotations

import math

OPTION_SPECS: list[dict] = [
    # ---- basic (rendered in the panel body, not behind the toggle) ----
    {
        "name": "time_box", "cli": "--time-box", "type": "float",
        "default": 300.0, "min": 1.0, "max": 86400.0, "advanced": False,
        "group": "budget", "label": "Time-box (s)",
        "help": "Total wall-clock budget for the k-walk. The panel edits this "
                "in minutes; the CLI default is 21600 (6 h).",
    },
    {
        "name": "seed_polish", "cli": "(webapp only)", "type": "int",
        "default": 0, "min": 0, "max": 64, "advanced": False,
        "group": "budget", "label": "Seed-polish (0 = off)",
        "help": "After the search, re-solve the best skeleton under this many "
                "CP-SAT seeds and keep a strictly lower road count. probe() has "
                "no objective, so the road count varies by solver seed. Costs up "
                "to seed_polish x probe-limit extra seconds; 0 = off.",
    },
    {
        "name": "exact_repair", "cli": "--exact-repair", "type": "float",
        "default": 5.0, "min": 0.0, "max": 300.0, "advanced": True,
        "group": "budget", "label": "Exact filler repair (s, 0 = off)",
        "help": "When CP-SAT places every road-needing building but the greedy "
                "filler packer cannot fit the rest, the layout is thrown away "
                "whole (SAT_FILLER_FAIL). This gives an exact CP-SAT rectangle "
                "packer that many seconds to rescue it, hinted with the greedy "
                "answer so it can never do worse. Runs only on layouts that "
                "would otherwise be discarded, and is clamped to the probe "
                "limit so a rescue can at most double one probe; 0 = off.",
    },
    {
        "name": "objective_limit", "cli": "--objective-limit", "type": "float",
        "default": 0.0, "min": 0.0, "max": 300.0, "advanced": True,
        "group": "budget", "label": "Placement objective (s, 0 = off)",
        "help": "After each feasible probe, spend up to this many seconds "
                "re-placing the road-needing buildings to minimise the road "
                "cells they actually need, starting from the feasible answer "
                "(so it can never do worse). Clamped to the probe limit; 0 = off.",
    },
    {
        "name": "objective_polish", "cli": "--objective-polish", "type": "float",
        "default": 0.0, "min": 0.0, "max": 0.9, "advanced": True,
        "group": "budget", "label": "Objective polish (share of box, 0 = off)",
        "help": "Reserve this share of the time box, after the search, to "
                "re-place buildings on the best few skeletons found using every "
                "solver thread, minimising the roads they need. Keeps only a "
                "strictly better, fully valid layout; 0 = off.",
    },
    {
        "name": "probe_model", "cli": "--probe-model", "type": "choice",
        "default": "position", "choices": ["item", "position"], "advanced": True,
        "group": "search", "label": "CP-SAT model",
        "help": "position (default): one switch per (building size, spot), so "
                "identical buildings are not told apart -- removes the symmetry "
                "that stalls the solver on cities with many same-size buildings, "
                "and the only model that places two-lane road tiles. item: one "
                "variable pair per building (historical).",
    },
    {
        "name": "military", "cli": "--military", "type": "choice",
        "default": "connect", "choices": ["connect", "unconnected"], "advanced": True,
        "group": "search", "label": "Two-lane buildings",
        "help": "connect (default): a building that needs a two-lane road gets a "
                "2x2 two-lane tile touching the Town Hall, as the game requires. "
                "unconnected: leave it off the road (it is packed like a "
                "decoration) -- your explicit choice, shown in the result.",
    },
    {
        "name": "rebase_s", "cli": "--rebase-s", "type": "float",
        "default": 0.0, "min": 0.0, "max": 300.0, "advanced": True,
        "group": "budget", "label": "Rebased polish (s, 0 = off)",
        "help": "After objective polish, re-place the buildings of the best "
                "layout on the roads it actually uses (cells the first road "
                "skeleton no longer needs become free spots). Takes this many "
                "seconds from the end of the polish time; keeps only a strictly "
                "better, fully valid layout. 0 = off.",
    },
    {
        "name": "road_witness", "cli": "--road-witness", "type": "bool",
        "default": False, "advanced": True,
        "group": "search", "label": "Keep the solver's roads",
        "help": "After each placement objective, also try the road network the "
                "solver itself selected, and keep it when it is smaller than the "
                "greedy re-route and every building still fits.",
    },
    {
        "name": "fillers_in_model", "cli": "--fillers-in-model", "type": "bool",
        "default": False, "advanced": True,
        "group": "search", "label": "Place decorations in the model",
        "help": "The placement solver also places the buildings that need no "
                "road, so every placement it finds leaves room for them. Needed "
                "for very full cities; makes each solve larger.",
    },
    {
        "name": "seed_input", "cli": "--seed-input", "type": "bool",
        "default": False, "advanced": True,
        "group": "search", "label": "Start from my city",
        "help": "If your uploaded city is game-legal, it is the first result, and "
                "the final polish tries to improve it on its own roads. Useful "
                "when the search finds no layout of its own.",
    },
    {
        "name": "scheduler", "cli": "--scheduler", "type": "choice",
        "default": "batch", "choices": ["batch", "queue"], "advanced": True,
        "group": "parallelism", "label": "Work scheduler",
        "help": "batch (default): probe a batch of k levels, wait for all of it, "
                "and restart the workers when a level runs out of time. queue: "
                "the workers stay up and are fed from one queue across levels; "
                "a level that runs out of time stops its solves cooperatively "
                "instead of discarding them. Same search decisions.",
    },
    {
        "name": "early_publish", "cli": "--early-publish", "type": "bool",
        "default": False, "advanced": True,
        "group": "parallelism", "label": "Show layouts sooner",
        "help": "With the queue scheduler: show each feasible layout as soon as "
                "it is checked (about a second), then the improved one when the "
                "placement objective finishes. Ignored with the batch scheduler.",
    },
    {
        "name": "exact_finish", "cli": "--exact-finish", "type": "bool",
        "default": False, "advanced": True,
        "group": "budget", "label": "Exact road finish",
        "help": "Re-route the final layout with the exact minimum-roads router "
                "(usually well under a second) and keep it if it uses fewer roads.",
    },
    {
        "name": "closure", "cli": "--closure", "type": "choice",
        "default": "bfs", "choices": ["bfs", "layered", "flow"], "advanced": True,
        "group": "budget", "label": "Polish: road connectivity rule",
        "help": "How the end-of-run polishes keep the chosen road cells joined "
                "to the Town Hall. bfs (default): one fixed path per cell, exact "
                "on tree-shaped skeletons. layered: any path that gets closer to "
                "the Town Hall at every step. flow: any connected network (exact, "
                "a larger model).",
    },
    {
        "name": "union_polish", "cli": "--union-polish", "type": "float",
        "default": 0.0, "min": 0.0, "max": 600.0, "advanced": True,
        "group": "budget", "label": "Union polish (s, 0 = off)",
        "help": "After objective polish, re-place the buildings on the UNION of "
                "the best road networks found around the same Town Hall spot, so "
                "the result can keep part of one network and part of another. "
                "Takes this many seconds from the end of the polish time (before "
                "rebased polish); keeps only a strictly better, fully valid "
                "layout. 0 = off.",
    },
    {
        "name": "union_m", "cli": "--union-m", "type": "int",
        "default": 3, "min": 2, "max": 8, "advanced": True,
        "group": "budget", "label": "Union polish: networks per union",
        "help": "How many of the best networks around one Town Hall spot the "
                "first union combines.",
    },
    {
        "name": "polish_top", "cli": "--polish-top", "type": "int",
        "default": 3, "min": 1, "max": 32, "advanced": True,
        "group": "budget", "label": "Objective polish: skeletons",
        "help": "How many of the best distinct skeletons objective polish "
                "re-solves. With parallel polish, more fit in the same time.",
    },
    {
        "name": "polish_parallel", "cli": "--polish-parallel", "type": "int",
        "default": 0, "min": 0, "max": 32, "advanced": True,
        "group": "budget", "label": "Objective polish: at once (0 = one by one)",
        "help": "Solve up to this many polish skeletons at the same time, "
                "splitting the solver threads between them, against the same "
                "deadline. The best result wins. 0 or 1 = one at a time.",
    },
    {
        "name": "polish_threads", "cli": "--polish-threads", "type": "int_or_null",
        "default": None, "min": 1, "max": 256, "advanced": True,
        "group": "budget", "label": "Objective polish: threads (blank = auto)",
        "help": "Solver threads the polish phase uses in total (the search "
                "workers idle meanwhile). Blank = workers x threads per probe.",
    },
    {
        "name": "exact_finish_workers", "cli": "--exact-finish-workers", "type": "int",
        "default": 0, "min": 0, "max": 64, "advanced": True,
        "group": "budget", "label": "Exact finish threads (0 = classic)",
        "help": "Solver threads for the exact road finish, started from the "
                "current roads so it can only match or beat them. 0 = the "
                "classic single-thread cold start.",
    },
    # ---- search shape ----
    {
        "name": "patterns", "cli": "--patterns", "type": "int",
        "default": 200, "min": 1, "max": 100000,
        "group": "search", "label": "Patterns per k",
        "help": "How many skeletons to sample at each road count k. Feasibility "
                "at record-setting k is ~1%, so this is the main statistical-power "
                "lever: more patterns finds the left tail.",
    },
    {
        "name": "probe_limit", "cli": "--probe-limit", "type": "float",
        "default": 60.0, "min": 1.0, "max": 3600.0,
        "group": "search", "label": "Probe limit (s)",
        "help": "CP-SAT time limit for one pattern's placement probe. Too low and "
                "feasible patterns come back UNKNOWN and are never detected.",
    },
    {
        "name": "k_start", "cli": "--k-start", "type": "int_or_auto",
        "default": "auto", "min": 1, "max": 100000,
        "group": "search", "label": "k start",
        "help": "Road count to start the walk from. 'auto' derives it from the "
                "current layout's road estimate.",
    },
    {
        "name": "th_anchors", "cli": "--th-anchors", "type": "choice",
        "default": "full", "choices": ["coarse", "full"],
        "group": "search", "label": "Town-hall anchors",
        "help": "Which town-hall offsets pattern generation may anchor on. "
                "'full' explores every offset (webapp default); 'coarse' is the "
                "cheaper CLI default.",
    },
    # ---- pattern family ----
    {
        "name": "pattern_family", "cli": "--pattern-family", "type": "choice",
        "default": "comb", "choices": ["comb", "lane", "nonuniform"],
        "group": "patterns", "label": "Pattern family",
        "help": "Skeleton generator. 'comb' = spine with teeth; 'lane' = straight "
                "double-loaded lanes; 'nonuniform' = lanes with irregular spacing "
                "and unequal branch lengths -- holds the records on both measured "
                "cities (darkzig 94, FR16 76). Pair it with the quality band.",
    },
    {
        "name": "comb_modes", "cli": "--comb-modes", "type": "choice",
        "default": "alternate", "choices": ["alternate", "both", "off"],
        "group": "patterns", "label": "Comb branch mode",
        "help": "Which branch policy the 'comb' family may emit. 'alternate' "
                "grows one tooth per seed; 'both' grows two. Defaults to "
                "'alternate' on measurement: at equal 600 s boxes FR16 goes "
                "90 -> 82 and FR17 goes from finding NOTHING to 124. In pooled "
                "probe logs 'both' is 0-for-528. 'off' emits both, which is the "
                "historical behaviour and reproduces pre-2026-08-01 records.",
    },
    {
        "name": "lane_cap", "cli": "--lane-cap", "type": "int_or_null",
        "default": None, "min": 1, "max": 1000,
        "group": "patterns", "label": "Lane cap (blank = none)",
        "help": "Maximum lane length for the 'lane' family. Ignored by 'comb'.",
    },
    {
        "name": "stub_priority", "cli": "--stub-priority", "type": "bool",
        "default": False,
        "group": "patterns", "label": "Stub priority",
        "help": "Hint CP-SAT to fill dead-end stub cells first, so a stub road "
                "cell serves three buildings instead of two.",
    },
    {
        "name": "symmetry_breaking", "cli": "--symmetry-breaking", "type": "bool",
        "default": False,
        "group": "patterns", "label": "Symmetry breaking",
        "help": "Add symmetry-breaking constraints between identically sized "
                "buildings. Shrinks the search tree; can also hide solutions.",
    },
    {
        "name": "quality_index_band", "cli": "--quality-index", "type": "choice",
        "default": "3,4", "choices": ["off", "3,4", "2,5"],
        "group": "patterns", "label": "Quality band",
        "help": "Keep only skeletons whose losses-2c index falls in the band. "
                "Every record this project holds sits at 3-4 on both cities "
                "despite different budgets; layouts at 2 are measurably worse. "
                "Took the darkzig SAT rate from 47% to ~100% at equal quality. "
                "Applies to the 'nonuniform' family. On by default: at a 900 s "
                "box it is worth nothing on darkzig (101 either way) and is the "
                "difference between finding NOTHING and matching the all-time "
                "record on FR16 (76).",
    },
    {
        "name": "lane_pitches", "cli": "--pitches", "type": "choice",
        "default": "off", "choices": ["off", "12-18", "5-18"],
        "group": "patterns", "label": "Lane pitch range",
        "help": "Widen the lane family's trunk-seed spacing beyond its built-in "
                "5-11. The default range was truncated at exactly its best value "
                "-- 12-18 exposes ~93k patterns per budget that were never "
                "reachable. Applies to the 'lane' family.",
    },
    # ---- parallelism ----
    {
        "name": "workers", "cli": "--workers", "type": "int",
        "default": 6, "min": 1, "max": 64,
        "group": "parallelism", "label": "Pattern workers",
        "help": "Processes probing patterns in parallel. workers x probe-workers "
                "is your total CP-SAT thread count: 16 threads leaves no core "
                "headroom and reproducibly regresses the walk (lessons 2026-07-19/20).",
    },
    {
        "name": "probe_workers", "cli": "--probe-workers", "type": "int",
        "default": 2, "min": 1, "max": 64,
        "group": "parallelism", "label": "Threads per probe",
        "help": "CP-SAT search threads inside a single probe. See the note on "
                "pattern workers -- 6 x 2 is the validated webapp default.",
    },
    {
        "name": "concurrent_levels", "cli": "(webapp only)", "type": "int",
        "default": 4, "min": 1, "max": 16,
        "group": "parallelism", "label": "Concurrent k levels",
        "help": "How many k levels to screen at once. A reproducible "
                "same-result/faster win with no observed downside (lessons 2026-07-20/21).",
    },
    # ---- warm start ----
    {
        "name": "warm_start", "cli": "--warm-start", "type": "bool",
        "default": False,
        "group": "warm_start", "label": "Warm start",
        "help": "Repack the city first and feed the resulting positions to "
                "CP-SAT as placement hints. Costs the warm-start budget up front.",
    },
    {
        "name": "warm_start_budget", "cli": "--warm-start-budget", "type": "float",
        "default": 30.0, "min": 1.0, "max": 3600.0,
        "group": "warm_start", "label": "Warm-start budget (s)",
        "help": "Seconds given to the repack that produces the hints. Ignored "
                "unless warm start is on.",
    },
]

GROUP_LABELS: dict[str, str] = {
    "budget": "Budget",
    "search": "Search",
    "patterns": "Patterns",
    "parallelism": "Parallelism",
    "warm_start": "Warm start",
}

# --smoke: not a parameter but a preset of them (see exp_roads_first.main).
SMOKE_PRESET: dict = {
    "patterns": 20, "probe_limit": 20.0, "time_box": 600.0,
    "workers": 1, "probe_workers": 1,
}

# The best settings for a USER-FACING run -- ON THE CITIES THEY WERE CALIBRATED
# ON. The skeleton family and quality band hold this project's records on darkzig
# (94 roads / 121% efficiency) and FR16 (76 / 116%).
#
# **They are not established as universal, and a third city disagrees.** On FR17
# the old `comb` family reaches 123 where this configuration reaches 124, the
# quality band makes k=137 infeasible outright (comb and the unbanded family both
# solve it), and the family-aware k_start lands ~16 levels below FR17's
# feasibility window, spending roughly half a short box climbing back up.
# darkzig and FR16 agreed on every lever, which made two-city tuning look
# general. See tasks/lessons.md 2026-07-31 ("The third city disagrees").
#
# Practical reading: try this preset first -- it is a large win on 2 of the 3
# cities measured and roughly neutral on the third -- but `pattern_family=comb`
# is a reasonable thing to try when it disappoints.
#
# probe_limit is deliberately 30 s, NOT the 300 s the research runs used. The
# k-walk checks its deadline only AFTER a probe returns (there is no mid-probe
# interruption), so a probe_limit at or above the time box overruns it: measured
# at a 120 s box, probe_limit 300 took 292 s (2.43x) while 10/20/40 s all took
# 121 s (1.01x) and reached IDENTICAL quality. Short probes cost nothing for this
# family -- unlike the lane family, where 30 s missed every known-feasible
# pattern (tasks/lessons.md 2026-07-22).
#
# seed_polish is 0 here, NOT the 12 the research runs used. It used to run after
# the walk with no deadline check (bounded by its own parameter, not the box);
# since 2026-07-31 it is budget-bounded (reserve + should_stop), but it still
# does not pay inside a short box: a reserve that fits a seed starves the walk.
# Measured at a 120 s box, before the fix: seed_polish=0 took 127 s (1.06x) and reached
# 101 roads; seed_polish=12 took 281 s (2.34x) and reached 100 -- 154 extra
# seconds for ONE road. It is a genuine lever for long runs (it produced the 94
# and the 95) and remains available; it is simply a bad trade inside a user box.
#
# exact_repair is 5.0 -- ON, unlike the two knobs above, because it is the one
# extra phase that is genuinely cheap. Measured over 116 real FR16 SATs: 19% of
# them died at SAT_FILLER_FAIL, 18 of those 22 were rescued, and the whole
# repair phase cost 2.53 s inside a 946 s run (0.27%). The 5 s budget is never
# approached on a normal city -- FR16 rescues took 0.11 s mean, 0.17 s worst --
# and it is clamped to probe_limit regardless.
#
# objective_limit is 30.0 (= probe_limit, the clamp) -- adopted 2026-11-11 from
# a 12-cell A/B, equal 600 s boxes, strictly sequential, paired repeats:
#     darkzig  off 99/99    on 94/94
#     FR16     off 77/77    on 75/74
#     FR17     off 115/115  on 115/109
# Never worse in any pair, better in 5 of 6.
#
# objective_polish 0.3 + exact_finish -- adopted from a second 12-cell round
# (same protocol). "on" = objective_limit only, shown after exact finish:
#               on        polish    both (adopted)
#     darkzig   93/93     90/90     91/91
#     FR16      75/74     73/73     73/73
#     FR17      114/108   114/107   108/108
# Both arms never worse than "on"; "both" has the best worst case and sum.
# Not measured below a 600 s box: at 60 s the reserve is 18 s of all-thread
# objective, unmeasured against a longer walk.
#
# probe_model "position" -- adopted from a third 12-cell round (same protocol,
# same preset otherwise): item vs position
#     darkzig   90/93    88/87
#     FR16      74/73    68/68
#     FR17      106/108  105/105
# Better in all 6 pairs, and every position run finished early (0.67-0.84x):
# levels are now DECIDED (often proven UNSAT in < 1 s) instead of timing out. It re-places each SAT minimising the
# skeleton cells it needs (minimize_needed), hinted from the feasible answer.
#
# What exact_repair does NOT do is improve the record: the rescued layouts tie the best
# greedy result at k=88 (78 roads, 3 such layouts -> 5) and are worse at k=92.
# It is a throughput lever -- ~16% more legal layouts per run for ~0.3% of the
# budget -- not a quality one.
#
# Expect ~101 roads on darkzig from a 2-minute box and ~76 on FR16 (its all-time
# record) -- not darkzig's 94, which needed ~10 core-hours of screening plus a
# 496-solve polish pass. 101 is a 60% cut on darkzig as found (250) and 36%
# better than the classical pipeline (158).
# rebase_s 20 (rebased polish, Codex T4) -- adopted 2026-11-12 from a 12-cell
# A/B, same protocol, all legal: preset vs preset + rebase_s=20
#               600 s               120 s
#     darkzig   91,92 -> 89,89      94,94 -> 88,91
#     FR16      68,68 -> 67,67      68,68 -> 67,67
#     FR17      103,103 -> 103,103  106,106 -> 106,106
# Never worse, better in 8 of 12 pairs; each rebase solve takes 0.3-14 s.
# road_witness (Codex T1) -- adopted 2026-11-12, preset (rebase) vs preset + witness:
#               600 s               120 s (paired)
#     darkzig   89,89 -> 88,88      89,91 -> 89,89
#     FR16      67,67 -> 67,67      67,67 -> 67,67
#     FR17      103,103 -> 103,103  106,106 -> 106,106
# Never worse, better in 3 of 10 pairs (all darkzig, within its +-2 noise at 120 s;
# the 600 s pair is consistent). 600 s baseline = the T4 A/B rows, same code flag-off.
# seed_input (Phase D) -- adopted 2026-11-16, preset (witness) vs preset + seed, 600 s:
#     darkzig   paired 90,89 -> 89,88 (unpaired 88,88 -> 89,89: darkzig noise is +-2)
#     FR16      67,67 -> 67,67      FR17   103,103 -> 103,103
#     FR24      none -> 228,220     user   none -> 142,142 (its own legal city back)
# A legal upload becomes the first incumbent, so rebased polish + exact finish run
# even when the walk finds nothing (FR24's first optimizer result, 232 -> 220).
# scheduler=queue + early_publish (S1+S3) -- adopted 2026-11-16 on feat/backlog-2026-11,
# preset vs qe (output/bench/2026-11-16-s1s2-120, s123q2-600):
#     600 s   darkzig 89,91 -> 88,88   FR16 67,67 -> 67,67   FR17 103,103 -> 103,103
#     120 s   darkzig 89,90 -> 90,88   FR16 67,67 -> 67,67   FR17 106,106 -> 104,104
# 600 s never worse (better 2, tie 4). 120 s has one darkzig pair worse by 1 (its +-2
# noise) against FR17 -2 in both pairs. First solver layout 31 s -> 1-2 s; walk idle
# 38-71% -> 2-4%. Mechanism: the batch walk overran into the polish reserve.
BEST_PRESET: dict = {
    "pattern_family": "nonuniform",
    "quality_index_band": "3,4",
    "th_anchors": "full",
    "patterns": 200,
    "probe_limit": 30.0,
    "seed_polish": 0,
    "concurrent_levels": 4,
    "exact_repair": 5.0,
    "comb_modes": "alternate",
    "objective_limit": 30.0,
    "objective_polish": 0.3,
    "exact_finish": True,
    "probe_model": "position",
    "rebase_s": 20.0,
    "road_witness": True,
    "seed_input": True,
    "scheduler": "queue",
    "early_publish": True,
}

DEFAULTS: dict = {s["name"]: s["default"] for s in OPTION_SPECS}
_BY_NAME: dict[str, dict] = {s["name"]: s for s in OPTION_SPECS}


class OptionError(ValueError):
    """A submitted run parameter is missing, mistyped, or out of range."""


def _as_number(spec: dict, raw, cast):
    kind = "an integer" if cast is int else "a number"
    bad = OptionError(f"{spec['name']}: expected {kind}, got {raw!r}")
    # bool is an int subclass: JSON true would otherwise become 1.
    if isinstance(raw, bool):
        raise bad
    try:
        value = float(raw) if cast is int else cast(raw)
    except (TypeError, ValueError, OverflowError):  # 10**400 -> OverflowError
        raise bad
    # NaN passes both range comparisons below (every comparison is False), and
    # inf would reach the solver as a time budget.
    if not math.isfinite(value):
        raise bad
    if cast is int:
        # int(2.7) silently truncates; a fractional "integer" is a client bug.
        if value != int(value):
            raise bad
        value = int(value)
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and value < lo:
        raise OptionError(f"{spec['name']}: must be >= {lo} (got {value})")
    if hi is not None and value > hi:
        raise OptionError(f"{spec['name']}: must be <= {hi} (got {value})")
    return value


def _coerce(spec: dict, raw):
    kind = spec["type"]
    if raw is None or raw == "":
        # blank clears a nullable field; for everything else it means "default"
        return None if kind == "int_or_null" else spec["default"]
    if kind == "int":
        return _as_number(spec, raw, int)
    if kind == "float":
        return _as_number(spec, raw, float)
    if kind == "int_or_null":
        return _as_number(spec, raw, int)
    if kind == "int_or_auto":
        if isinstance(raw, str) and raw.strip() == "auto":
            return "auto"
        return _as_number(spec, raw, int)
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        raise OptionError(f"{spec['name']}: expected a boolean, got {raw!r}")
    if kind == "choice":
        if raw not in spec["choices"]:
            raise OptionError(f"{spec['name']}: must be one of {spec['choices']} (got {raw!r})")
        return raw
    raise OptionError(f"{spec['name']}: unknown option type {kind!r}")  # pragma: no cover


def parse_options(data: dict) -> dict:
    """Coerce a request body into JobManager.submit kwargs.

    Unknown keys are ignored (the body also carries city_id); absent keys fall
    back to the spec default. Raises OptionError -- caught by /api/optimize and
    returned as a 400 -- when a value is the wrong type or out of range.
    """
    return {name: (_coerce(spec, data[name]) if name in data else spec["default"])
            for name, spec in _BY_NAME.items()}
