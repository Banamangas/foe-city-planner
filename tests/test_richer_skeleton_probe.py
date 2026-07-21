import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "exp_richer_skeleton_probe",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_richer_skeleton_probe.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _row(family, status, achieved=None, legal=None):
    return {"family": family, "k": 100, "status": status, "achieved": achieved, "legal": legal}


def test_verdict_break_floor_on_legal_sub_102_sat():
    rows = [_row("lane", "SAT", achieved=100, legal=True), _row("comb", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "BREAK_FLOOR"


def test_verdict_feasibility_wall_when_sats_are_at_or_above_floor():
    # a lane SAT that lands at 106 (feasible but not below comb) is a wall, not a win.
    rows = [_row("lane", "SAT", achieved=106, legal=True), _row("hybrid", "UNSAT"),
            _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "FEASIBILITY_WALL"


def test_verdict_decidability_wall_when_unknown_dominated():
    rows = [_row("lane", "UNKNOWN"), _row("hybrid", "UNKNOWN"), _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)  # 2/3 richer UNKNOWN >= 0.5
    assert verdict == "DECIDABILITY_WALL"


def test_verdict_ignores_illegal_sub_102_sat():
    # a sub-102 SAT that is not legal (rotated) must NOT trigger BREAK_FLOOR.
    rows = [_row("lane", "SAT", achieved=99, legal=False), _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "FEASIBILITY_WALL"


def test_verdict_control_comb_excluded_from_richer_tally():
    # comb is a control; only lane/hybrid drive the verdict.
    rows = [_row("comb", "UNKNOWN"), _row("comb", "UNKNOWN"), _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "FEASIBILITY_WALL"     # richer = 1 lane UNSAT, 0 unknown
