"""Throwaway CLI for foeopt.minroads (next-things-to-try #6 tractability
gate). Usage:
  uv run --extra rl python scripts/exp_minroads.py --selftest
  uv run --extra rl python scripts/exp_minroads.py darkzig.json --time-limit 300
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout


def _selftest() -> int:
    import subprocess
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/test_minroads.py", "-q"],
                         capture_output=True, text=True)
    print(out.stdout)
    print(out.stderr)
    return out.returncode


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city", nargs="?")
    p.add_argument("--time-limit", type=float, default=300.0)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.city is None:
        p.error("city is required (or use --selftest)")

    layout = load_layout(args.city)
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    print(f"region cells: {len(region)}, consumers: {len(consumers)}", flush=True)

    from foeopt.minroads import solve_min_roads
    t0 = time.monotonic()
    st, roads, positions = solve_min_roads(layout, region, time_limit=args.time_limit)
    secs = time.monotonic() - t0
    print(f"status={st} secs={secs:.1f} roads={len(roads) if roads else None}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
