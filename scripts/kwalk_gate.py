"""Track C-bis Stage 1 G1 gate driver.

Usage:
  # train on the Stage-0 corpora, save a checkpoint, print held-out ROC-AUC:
  uv run --extra rl python scripts/kwalk_gate.py train \
      --corpus output/corpus/darkzig output/corpus/FR16 --out output/kwalk/cnn.pt

  # baseline k-walk (no model) vs guided (with model), equal wall-clock:
  uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 3600
  uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 3600 \
      --scorer output/kwalk/cnn.pt

G1 passes iff held-out AUC >= 0.80 AND the guided walk reaches k <= 104
(or 106 in <= 50% of the baseline's wall-clock).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _train(args):
    from rl.kwalk_eval import evaluate
    from rl.kwalk_data import build_samples
    from rl.kwalk_classifier import train, save
    res = evaluate(args.corpus, epochs=args.epochs, seed=args.seed)
    samples = build_samples(args.corpus)
    model = train(samples, epochs=args.epochs, seed=args.seed)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save(model, out, samples["H"], samples["W"])
    print(json.dumps({**res, "checkpoint": str(out),
                      "G1_auc_pass": res["auc"] >= 0.80}, indent=1))
    return 0


def _walk(args):
    from foeopt.loader import load_layout
    from foeopt.roads_first import RoadsFirstSearch
    layout = load_layout(args.city)
    scorer = None
    if args.scorer:
        from rl.kwalk_scorer import PatternScorer
        scorer = PatternScorer(args.scorer, layout)
    res = RoadsFirstSearch(
        layout, time_box=args.time_box, patterns=args.patterns,
        probe_limit=args.probe_limit, workers=args.workers,
        probe_workers=args.probe_workers, th_anchors=args.th_anchors,
        scorer=scorer, score_threshold=args.score_threshold,
    ).run(on_status=lambda k, s, *_: print(f"  k={k}: {s}", flush=True))
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, indent=1))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Track C-bis Stage 1 G1 gate driver")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--corpus", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--epochs", type=int, default=40)
    t.add_argument("--seed", type=int, default=0)
    t.set_defaults(fn=_train)
    w = sub.add_parser("walk")
    w.add_argument("city")
    w.add_argument("--scorer", default=None)
    w.add_argument("--score-threshold", type=float, default=None)
    w.add_argument("--time-box", type=float, default=3600.0)
    w.add_argument("--patterns", type=int, default=200)
    w.add_argument("--probe-limit", type=float, default=30.0)
    w.add_argument("--workers", type=int, default=6)
    w.add_argument("--probe-workers", type=int, default=2)
    w.add_argument("--th-anchors", choices=("coarse", "full"), default="full")
    w.set_defaults(fn=_walk)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
