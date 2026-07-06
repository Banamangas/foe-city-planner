"""LNS A/B (Track B spec section 8). Arm A: polish(R, N+L). Arm B:
lns_polish(R, N, L). Identical wall-clock per seed. Gate: darkzig mean
0-unplaced roads >=2 better in B AND max(B) <= max(A); B's per-run
before/after HTML goes to output/lns/<run-stamp>/.

  uv run python scripts/exp_lns_ab.py darkzig.json --seeds 8
"""
import pathlib
import sys
import time
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ab_common import base_parser, load_cities, summarize
from foeopt.lns import lns_polish
from foeopt.polish import polish
from foeopt.viz import render_comparison

R_FRAC, N_FRAC, L_FRAC = 0.5, 0.25, 0.25      # of --budget (default 120 -> 60/30/30)


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = pathlib.Path("output") / "lns" / stamp
    for name, lay in load_cities(args.city, args.helper, args.fills):
        R, N, L = (args.budget * f for f in (R_FRAC, N_FRAC, L_FRAC))
        rows_a, rows_b = [], []
        for seed in range(args.seeds):
            t0 = time.monotonic()
            a = polish(lay, repack_budget=R, anneal_budget=N + L, seed=seed)
            rows_a.append({"seed": seed, "unplaced": len(a.unplaced),
                           "roads": len(a.layout.roads), "trials": a.trials,
                           "secs": round(time.monotonic() - t0, 1)})
            t0 = time.monotonic()
            b = lns_polish(lay, repack_budget=R, anneal_budget=N,
                           lns_budget=L, seed=seed)
            rows_b.append({"seed": seed, "unplaced": len(b.final.unplaced),
                           "roads": len(b.final.layout.roads),
                           "trials": b.final.trials, "accepted": b.accepted,
                           "secs": round(time.monotonic() - t0, 1)})
            out_dir.mkdir(parents=True, exist_ok=True)
            safe = name.replace(" ", "_").replace("=", "")
            (out_dir / f"{safe}-seed{seed}.html").write_text(
                render_comparison(b.base_layout, b.final.layout), encoding="utf-8")
        summarize(f"{name} lns=off", rows_a)
        summarize(f"{name} lns=on ", rows_b)
        acc = [r["accepted"] for r in rows_b]
        print(f"  lns accepted rewrites per seed: {acc}")


if __name__ == "__main__":
    main()
