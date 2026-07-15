import numpy as np
import pytest

from rl.kwalk_eval import roc_auc, split


def test_roc_auc_perfect_and_random():
    y = np.array([0, 0, 1, 1])
    assert roc_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    mid = roc_auc(np.array([0, 1, 0, 1]), np.array([0.5, 0.5, 0.5, 0.5]))
    assert abs(mid - 0.5) < 1e-9


def test_split_is_stratified():
    s = {"X": np.zeros((100, 4, 4, 4), np.float32), "g": np.zeros((100, 9), np.float32),
         "y": np.array([0, 1] * 50, dtype=np.float32), "H": 4, "W": 4}
    tr, va = split(s, frac=0.2, seed=0)
    assert va["y"].shape[0] == 20 and tr["y"].shape[0] == 80
    assert abs(va["y"].mean() - 0.5) < 0.2       # both classes present in val
