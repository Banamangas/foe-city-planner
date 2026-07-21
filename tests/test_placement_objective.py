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
