import importlib.util, json, pathlib, sys

import pytest

_spec = importlib.util.spec_from_file_location(
    "exp_wide_skeleton_screen",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_wide_skeleton_screen.py",
)
mod = importlib.util.module_from_spec(_spec)
# Register under its own name before exec so multiprocessing can pickle
# module-level functions by reference (needed for the Pool-based recheck
# test, which is the first test in this file to actually dispatch a Pool).
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


@pytest.fixture(autouse=True)
def _restore_worker_globals():
    saved = dict(mod._W)
    yield
    mod._W.clear()
    mod._W.update(saved)


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


def test_sat_artifact_matches_best_k_schema(tmp_path):
    """SAT artifacts must be consumable by exp_exact_router.reconstruct_fixed
    unchanged -- that is how a floor-breaking layout gets independently
    re-verified. reconstruct_fixed reads best["buildings"] as
    {str(entity_id): [x, y, w, l]}."""
    from foeopt.model import Building, Footprint, Layout, Region
    from foeopt.roads_first import Pattern
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(2, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    vlay = Layout(region, [th, c1], th, {})
    vlay.roads = [(0, 2), (1, 2)]
    pat = Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2), (1, 2)}),
                  params={"th": (0, 0), "k": 2})
    art = mod._sat_artifact(105, 3, pat, vlay, 2)
    assert art["k"] == 105 and art["idx"] == 3 and art["achieved"] == 2
    assert art["buildings"] == {"1": [0, 0, 2, 2], "2": [2, 0, 2, 1]}
    assert sorted(art["roads"]) == [[0, 2], [1, 2]]
    assert sorted(art["pattern_roads"]) == [[0, 2], [1, 2]]
    # every key reconstruct_fixed touches must be JSON round-trippable
    assert json.loads(json.dumps(art))["buildings"]["1"] == [0, 0, 2, 2]


def test_persist_sat_writes_identifiable_filename(tmp_path):
    art = {"k": 106, "idx": 42, "achieved": 101, "th": [1, 1, 2, 2],
           "pattern_roads": [], "roads": [], "buildings": {}}
    p = mod.persist_sat(tmp_path, art)
    assert p.exists()
    assert p.name == "sat-k106-i42-a101.json"
    assert json.loads(p.read_text())["achieved"] == 101


def test_screen_one_uses_validate_status_verbatim(monkeypatch):
    """validate() already returns terminal statuses; re-prefixing them would
    emit SAT_SAT_ROTATED and corrupt an unattended run's record."""
    from foeopt.model import Footprint
    from foeopt.roads_first import Pattern
    pat = Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2)}),
                  params={"th": (0, 0), "k": 1})
    mod._W.update({"layout": object(), "region": set(), "consumers": [], "budget": 1.0})
    monkeypatch.setattr(mod, "probe", lambda *a, **k: ("SAT", {}))
    monkeypatch.setattr(mod, "validate", lambda *a: ("SAT_ROTATED", None, 0))
    row, art = mod._screen_one((105, 0, pat))
    assert row["status"] == "SAT_ROTATED"
    assert art is None
    monkeypatch.setattr(mod, "validate", lambda *a: ("ROUTE_FAIL", None, 0))
    row, art = mod._screen_one((105, 0, pat))
    assert row["status"] == "ROUTE_FAIL"
    assert art is None


def test_screen_one_passes_through_non_sat_probe_status(monkeypatch):
    from foeopt.model import Footprint
    from foeopt.roads_first import Pattern
    pat = Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2)}),
                  params={"th": (0, 0), "k": 1})
    mod._W.update({"layout": object(), "region": set(), "consumers": [], "budget": 1.0})
    monkeypatch.setattr(mod, "probe", lambda *a, **k: ("UNKNOWN", None))
    row, art = mod._screen_one((106, 4, pat))
    assert row["status"] == "UNKNOWN" and art is None
    assert row["k"] == 106 and row["idx"] == 4
    assert row["achieved"] is None and row["legal"] is None


def test_summarize_tallies_per_k_and_carries_verdict():
    rows = [
        {"k": 105, "idx": 0, "status": "UNSAT", "achieved": None, "legal": None, "reason": "presolve"},
        {"k": 105, "idx": 1, "status": "UNKNOWN", "achieved": None, "legal": None, "reason": "search"},
        {"k": 106, "idx": 0, "status": "SAT", "achieved": 101, "legal": True, "reason": "search"},
        {"k": 106, "idx": 1, "status": "PREFILTERED", "achieved": None, "legal": None, "reason": "prefilter:area"},
    ]
    s = mod.summarize(rows)
    assert s["per_k"][105]["UNSAT"] == 1 and s["per_k"][105]["UNKNOWN"] == 1
    assert s["per_k"][106]["SAT"] == 1 and s["per_k"][106]["PREFILTERED"] == 1
    assert s["per_k"][106]["min_achieved"] == 101
    assert s["per_k"][105]["min_achieved"] is None
    assert s["verdict"] == "BREAK_FLOOR"
    assert s["detail"]["best_achieved"] == 101


def test_read_rows_tolerates_torn_and_malformed_lines(tmp_path):
    """The summary read must survive a kill -9 as load_done does; otherwise an
    8h screen could complete and still lose its summary to one torn line."""
    p = tmp_path / "rows.jsonl"
    p.write_text('{"k": 105, "idx": 0, "status": "UNSAT"}\n'
                 '\n'
                 '{"status": "UNSAT"}\n'
                 '{"k": 105, "idx": 1, "status": "UNKNOWN"}\n'
                 '{"k": 105, "idx')
    rows = mod.read_rows(p)
    assert [(r["k"], r["idx"]) for r in rows] == [(105, 0), (105, 1)]


def test_read_rows_missing_file_is_empty(tmp_path):
    assert mod.read_rows(tmp_path / "nope.jsonl") == []


def test_summarize_buckets_unknown_status_names_under_other():
    """validate()'s terminal statuses and any future status must land in
    `other`, and must never collide with the 'n'/'min_achieved' bookkeeping."""
    rows = [
        {"k": 105, "idx": 0, "status": "SAT_ROTATED", "achieved": None, "legal": None},
        {"k": 105, "idx": 1, "status": "ROUTE_FAIL", "achieved": None, "legal": None},
        {"k": 105, "idx": 2, "status": "UNSAT", "achieved": None, "legal": None},
    ]
    s = mod.summarize(rows)
    d = s["per_k"][105]
    assert d["n"] == 3
    assert d["other"] == 2
    assert d["UNSAT"] == 1
    assert d["SAT"] == 0 and d["UNKNOWN"] == 0 and d["PREFILTERED"] == 0
    # every row incremented exactly one bucket
    assert d["SAT"] + d["UNSAT"] + d["UNKNOWN"] + d["PREFILTERED"] + d["other"] == d["n"]


def test_pick_recheck_targets_samples_only_unknowns(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"k": 105, "idx": 0, "status": "UNSAT"},
        {"k": 105, "idx": 1, "status": "UNKNOWN"},
        {"k": 106, "idx": 2, "status": "UNKNOWN"},
        {"k": 106, "idx": 3, "status": "SAT"},
        {"k": 106, "idx": 4, "status": "PREFILTERED"},
    ]) + "\n")
    picked = mod.pick_recheck_targets(p, sample_n=2, seed=0)
    assert len(picked) == 2
    assert set(picked) <= {(105, 1), (106, 2)}
    # deterministic for a fixed seed
    assert picked == mod.pick_recheck_targets(p, sample_n=2, seed=0)


def test_run_recheck_regenerates_by_index_and_persists_sats(tmp_path):
    """The recheck regenerates patterns from (k, idx) alone. If that mapping
    broke, the arm would confidently re-probe the WRONG patterns and give a
    wrong answer about whether the 30s budget is sound."""
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(10) for y in range(10)))
    layout = Layout(region, [th, c1], th, {})

    rows_path = tmp_path / "rows.jsonl"
    rows_path.write_text("\n".join(json.dumps(r) for r in [
        {"k": 6, "idx": 0, "status": "UNKNOWN"},
        {"k": 6, "idx": 1, "status": "UNKNOWN"},
        {"k": 6, "idx": 2, "status": "UNSAT"},   # must not be picked
    ]) + "\n")
    sat_dir = tmp_path / "sats"
    res = mod.run_recheck(layout, rows_path, sample_n=2, budget=5.0, workers=2,
                          seed=0, n_per=6, sat_dir=sat_dir)
    assert res["n"] == 2
    assert {(r["k"], r["idx"]) for r in res["rows"]} == {(6, 0), (6, 1)}
    # any SAT the recheck finds must leave a reconstructable artifact on disk
    for r in res["rows"]:
        if r["status"] == "SAT":
            assert list(sat_dir.glob(f"sat-k{r['k']}-i{r['idx']}-*.json")), \
                "recheck found a SAT but persisted no artifact"


def test_read_rows_dedups_on_k_idx_last_wins(tmp_path):
    """A re-run appends rather than truncates and the recheck deliberately
    re-records rows. Without dedup the summary's n inflates and the
    rule-of-three bound is reported falsely tight."""
    p = tmp_path / "rows.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"k": 105, "idx": 0, "status": "UNKNOWN"},
        {"k": 105, "idx": 1, "status": "UNSAT"},
        {"k": 105, "idx": 0, "status": "SAT"},     # recheck resolved it: must win
    ]) + "\n")
    rows = mod.read_rows(p)
    assert len(rows) == 2
    assert {(r["k"], r["idx"]): r["status"] for r in rows} == {
        (105, 0): "SAT", (105, 1): "UNSAT"}
