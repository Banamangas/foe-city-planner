"""TH-offset probe (Track B spec section 8b). Pure-style arms: corner-only vs
offset-only (every trial th_style='offset'). Diagnostic only — no flip gate.

  uv run python scripts/exp_th_offset_ab.py darkzig.json --seeds 8
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ab_common import base_parser, load_cities, summarize
from foeopt.packer import repack


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    for name, lay in load_cities(args.city, args.helper, args.fills):
        for label, styles in (("corner", ("corner",)), ("offset", ("offset",))):
            rows = []
            for seed in range(args.seeds):
                t0 = time.monotonic()
                res = repack(lay, budget_seconds=args.budget, seed=seed,
                             th_styles=styles)
                rows.append({"seed": seed, "unplaced": len(res.unplaced),
                             "roads": len(res.layout.roads), "trials": res.trials,
                             "secs": round(time.monotonic() - t0, 1)})
            summarize(f"{name} th={label}", rows)


if __name__ == "__main__":
    main()
