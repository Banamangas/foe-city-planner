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
        "default": "off", "choices": ["off", "3,4", "2,5"],
        "group": "patterns", "label": "Quality band",
        "help": "Keep only skeletons whose losses-2c index falls in the band. "
                "Every record this project holds sits at 3-4 on both cities "
                "despite different budgets; layouts at 2 are measurably worse. "
                "Took the darkzig SAT rate from 47% to ~100% at equal quality. "
                "Applies to the 'nonuniform' family.",
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

# The configuration that holds this project's records on BOTH measured cities:
# darkzig 94 roads (121% efficiency, was 250 as found) and FR16 76 (116%).
# Measured against the previous best settings at equal probe count: SAT rate
# 46.7% -> 69.6%, and the screen alone reached 94 where the older filter needed a
# 496-solve polish pass. See tasks/lessons.md 2026-07-31.
BEST_PRESET: dict = {
    "pattern_family": "nonuniform",
    "quality_index_band": "3,4",
    "th_anchors": "full",
    "patterns": 200,
    "probe_limit": 300.0,
    "seed_polish": 12,
    "concurrent_levels": 4,
}

DEFAULTS: dict = {s["name"]: s["default"] for s in OPTION_SPECS}
_BY_NAME: dict[str, dict] = {s["name"]: s for s in OPTION_SPECS}


class OptionError(ValueError):
    """A submitted run parameter is missing, mistyped, or out of range."""


def _as_number(spec: dict, raw, cast):
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        raise OptionError(f"{spec['name']}: expected {'an integer' if cast is int else 'a number'}, got {raw!r}")
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
