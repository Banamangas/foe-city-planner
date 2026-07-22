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


def test_load_done_returns_k_idx_pairs(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text('{"k": 105, "idx": 0, "status": "UNSAT"}\n'
                 '{"k": 105, "idx": 7, "status": "UNKNOWN"}\n')
    assert mod.load_done(p) == {(105, 0), (105, 7)}


def test_load_done_missing_file_is_empty(tmp_path):
    assert mod.load_done(tmp_path / "nope.jsonl") == set()


def test_load_done_tolerates_torn_final_line(tmp_path):
    """An 8h run killed mid-write leaves a partial last line. Resume must
    skip it rather than crash, or the whole run is unrecoverable."""
    p = tmp_path / "rows.jsonl"
    p.write_text('{"k": 105, "idx": 0, "status": "UNSAT"}\n{"k": 105, "idx')
    assert mod.load_done(p) == {(105, 0)}


def test_sample_patterns_is_deterministic_and_sized():
    """Resume and the recheck arm both rely on (seed, n, k) reproducing the
    exact same patterns in the exact same order."""
    region = {(x, y) for x in range(20) for y in range(20)}
    a = mod.sample_patterns(region, 2, 2, 20, 5, seed=0)
    b = mod.sample_patterns(region, 2, 2, 20, 5, seed=0)
    assert len(a) == 5
    assert [p.roads for p in a] == [p.roads for p in b]
    c = mod.sample_patterns(region, 2, 2, 20, 5, seed=1)
    assert [p.roads for p in a] != [p.roads for p in c]


def test_load_done_skips_rows_missing_identity_keys(tmp_path):
    """load_done must never raise on a malformed results file -- a valid-JSON
    row missing k/idx would otherwise crash resume with KeyError, which is the
    exact failure this function exists to prevent."""
    p = tmp_path / "rows.jsonl"
    p.write_text('{"status": "UNSAT"}\n'
                 '{"k": 105, "idx": 2, "status": "UNSAT"}\n'
                 '[1, 2, 3]\n'
                 '{"k": 106, "status": "UNKNOWN"}\n')
    assert mod.load_done(p) == {(105, 2)}
