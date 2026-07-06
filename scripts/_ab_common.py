from __future__ import annotations

import argparse
import pathlib
import random
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from rl.curriculum import make_real_like_city


def base_parser(doc):
    p = argparse.ArgumentParser(description=doc)
    p.add_argument("city")
    p.add_argument("helper", nargs="?", default=None)
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--budget", type=float, default=120.0)
    p.add_argument("--fills", default="0.5,0.7,0.9",
                   help="real-like synthesis fills; empty string = city only")
    return p


def load_cities(city, helper, fills):
    ref = load_layout(city, helper)
    cities = [("city", ref)]
    for f in filter(None, fills.split(",")):
        cities.append((f"real-like fill={f}",
                       make_real_like_city(random.Random(0), ref, fill=float(f))))
    return cities


def summarize(name, rows):
    unp = [r["unplaced"] for r in rows]
    ok_roads = [r["roads"] for r in rows if r["unplaced"] == 0]
    trials = [r["trials"] for r in rows]
    print(f"{name}: unplaced min/mean/max {min(unp)}/{statistics.mean(unp):.1f}/{max(unp)}"
          f" | 0-unplaced roads {sorted(ok_roads) if ok_roads else 'NONE'}"
          f" | trials/run mean {statistics.mean(trials):.0f}")
