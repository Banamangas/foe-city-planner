from __future__ import annotations

import numpy as np


def roc_auc(y_true, scores) -> float:
    y = np.asarray(y_true)
    s = np.asarray(scores, dtype=np.float64)
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=np.float64)
    ranks[order] = np.arange(1, len(s) + 1)
    # average ranks for ties
    _, inv, counts = np.unique(s, return_inverse=True, return_counts=True)
    sum_ranks = np.zeros(len(counts))
    np.add.at(sum_ranks, inv, ranks)
    ranks = (sum_ranks / counts)[inv]
    rank_pos = ranks[y == 1].sum()
    n_pos, n_neg = len(pos), len(neg)
    return float((rank_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def split(samples, frac=0.2, seed=0):
    rng = np.random.default_rng(seed)
    y = samples["y"]
    val_idx = []
    for cls in (0, 1):
        idx = np.where(y == cls)[0]
        rng.shuffle(idx)
        val_idx.extend(idx[: int(round(len(idx) * frac))].tolist())
    val_mask = np.zeros(len(y), dtype=bool)
    val_mask[val_idx] = True

    def take(mask):
        return {"X": samples["X"][mask], "g": samples["g"][mask], "y": samples["y"][mask],
                "H": samples["H"], "W": samples["W"]}
    return take(~val_mask), take(val_mask)


def evaluate(corpus_dirs, *, epochs=30, seed=0):
    from rl.kwalk_data import build_samples
    from rl.kwalk_classifier import train, predict_proba
    s = build_samples(corpus_dirs)
    tr, va = split(s, seed=seed)
    model = train(tr, epochs=epochs, seed=seed)
    p = predict_proba(model, va["X"], va["g"])
    return {"auc": roc_auc(va["y"], p), "n_train": len(tr["y"]),
            "n_val": len(va["y"]), "H": s["H"], "W": s["W"]}
