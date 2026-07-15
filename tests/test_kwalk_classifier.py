import numpy as np
import pytest

torch = pytest.importorskip("torch")

from rl.kwalk_classifier import FeasibilityCNN, train, predict_proba, save, load


def _separable(n=120, H=8, W=8, seed=0):
    rng = np.random.default_rng(seed)
    X = np.zeros((n, 4, H, W), dtype=np.float32)
    g = rng.standard_normal((n, 9)).astype(np.float32)
    y = np.zeros(n, dtype=np.float32)
    for i in range(n):
        pos = i % 2
        y[i] = pos
        # class signal: positives have a dense skeleton channel, negatives sparse
        X[i, 1] = (rng.random((H, W)) < (0.5 if pos else 0.05)).astype(np.float32)
        g[i, 0] = pos * 5.0
    return {"X": X, "g": g, "y": y, "H": H, "W": W}


def test_train_separates_classes():
    ds = _separable()
    model = train(ds, epochs=40, seed=0)
    p = predict_proba(model, ds["X"], ds["g"])
    acc = ((p > 0.5).astype(np.float32) == ds["y"]).mean()
    assert acc >= 0.9


def test_save_load_roundtrip(tmp_path):
    ds = _separable(n=20)
    model = train(ds, epochs=2, seed=0)
    save(model, tmp_path / "m.pt", ds["H"], ds["W"])
    m2, H, W = load(tmp_path / "m.pt")
    assert (H, W) == (ds["H"], ds["W"])
    p1 = predict_proba(model, ds["X"], ds["g"])
    p2 = predict_proba(m2, ds["X"], ds["g"])
    assert np.allclose(p1, p2, atol=1e-5)
