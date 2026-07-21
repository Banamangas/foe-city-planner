import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "exp_placement_objective",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_placement_objective.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

def test_spearman_perfect_monotonic():
    assert mod.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0

def test_spearman_perfect_inverse():
    assert mod.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0

def test_spearman_handles_ties_without_crashing():
    r = mod.spearman([1, 1, 2, 2], [5, 5, 9, 9])
    assert 0.0 <= r <= 1.0

def test_spearman_too_short_is_zero():
    assert mod.spearman([1], [2]) == 0.0


def test_load_sat_skeletons_filters_and_reconstructs(tmp_path):
    import json
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"city_id": "x", "region": [[0, 0]], "buildings": []}))
    recs = [
        {"k": 10, "status": "UNSAT", "secs": 1, "th": [0, 0, 2, 2],
         "roads": [[2, 0]], "pos": None},
        {"k": 12, "status": "SAT", "secs": 1, "th": [3, 4, 2, 2],
         "roads": [[5, 5], [5, 6]], "pos": {"1": [0, 0, 1, 1]}},
    ]
    (d / "instances.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
    pats = mod.load_sat_skeletons(str(d))
    assert len(pats) == 1              # UNSAT record filtered out
    assert pats[0].params["k"] == 12
    assert (pats[0].th.x, pats[0].th.width) == (3, 2)
    assert pats[0].roads == frozenset({(5, 5), (5, 6)})
