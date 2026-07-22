import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "exp_wide_skeleton_screen",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_wide_skeleton_screen.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _row(status, achieved=None, legal=None, k=105, idx=0):
    return {"k": k, "idx": idx, "status": status, "achieved": achieved, "legal": legal}


def test_rule_of_three_bound():
    assert mod.rule_of_three(5000) == 3.0 / 5000
    assert mod.rule_of_three(100) == 0.03
    # a rate cannot exceed certainty: small n must clamp to 1.0, not exceed it
    assert mod.rule_of_three(3) == 1.0
    assert mod.rule_of_three(1) == 1.0
    # n=0 must not divide by zero
    assert mod.rule_of_three(0) == 1.0


def test_verdict_break_floor_on_legal_sub_102():
    rows = [_row("SAT", achieved=101, legal=True), _row("UNSAT")]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "BREAK_FLOOR"
    assert detail["best_achieved"] == 101


def test_verdict_tie_at_floor_is_not_a_win():
    # achieved == floor ties the record, it does not beat it
    rows = [_row("SAT", achieved=102, legal=True), _row("UNSAT")]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "FEASIBLE_NOT_SUPERIOR"
    assert detail["best_achieved"] == 102


def test_verdict_ignores_illegal_sat():
    # a rotated (illegal) sub-floor SAT must never trigger BREAK_FLOOR
    rows = [_row("SAT", achieved=99, legal=False), _row("UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "NULL_WITH_BOUND"


def test_verdict_null_reports_bound_over_all_screened_rows():
    # PREFILTERED rows are determinations too and must count toward n
    rows = [_row("UNSAT"), _row("UNKNOWN"), _row("PREFILTERED")]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "NULL_WITH_BOUND"
    assert detail["n"] == 3
    assert detail["p_bound"] == 1.0
    assert detail["best_achieved"] is None


def test_verdict_break_floor_wins_over_a_worse_sat():
    rows = [_row("SAT", achieved=104, legal=True), _row("SAT", achieved=100, legal=True)]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "BREAK_FLOOR"
    assert detail["best_achieved"] == 100


def test_detail_n_sat_counts_only_legal_validated_sats():
    rows = [_row("SAT", achieved=105, legal=True),
            _row("SAT", achieved=99, legal=False),   # illegal, must not count
            _row("SAT", achieved=None, legal=True),  # no achieved, must not count
            _row("UNKNOWN")]
    _, detail = mod.classify_verdict(rows)
    assert detail["n_sat"] == 1
    assert detail["n"] == 4


def test_custom_floor_is_respected():
    rows = [_row("SAT", achieved=101, legal=True)]
    assert mod.classify_verdict(rows, floor=100)[0] == "FEASIBLE_NOT_SUPERIOR"
    assert mod.classify_verdict(rows, floor=102)[0] == "BREAK_FLOOR"
