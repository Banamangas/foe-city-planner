from __future__ import annotations

import argparse
import json
from pathlib import Path

from foeopt.build import build_layout
from foeopt.router import route, RouteError
from foeopt.report import stats, road_diff
from foeopt.viz import render_html, render_comparison
from foeopt.packer import repack


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _cmd_view(args) -> int:
    layout = build_layout(_load(args.city), _load(args.helper))
    html = render_html(layout)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote map to {args.out} ({len(layout.buildings)} buildings, "
          f"{len(layout.roads)} roads)")
    return 0


def _cmd_roads(args) -> int:
    city = _load(args.city)
    helper = _load(args.helper)
    layout = build_layout(city, helper)
    try:
        optimized = route(layout)
    except RouteError as exc:
        print(f"ERROR: {exc}")
        return 2
    s = stats(layout, optimized)
    print("Road optimization (buildings fixed):")
    for k, v in s.items():
        print(f"  {k}: {v}")
    html = render_html(layout, optimized_roads=optimized)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote map to {args.out}")
    if args.diff:
        Path(args.diff).write_text(json.dumps(road_diff(layout.roads, optimized), indent=2))
        print(f"Wrote diff to {args.diff}")
    return 0 if s["unsatisfied"] == 0 else 1


def _cmd_layout(args) -> int:
    current = build_layout(_load(args.city), _load(args.helper))
    res = repack(current, thorough=args.thorough)
    s = stats(current, res.layout.roads)
    print("Full re-pack (Phase 2):")
    print(f"  buildings: {len(current.buildings)} | placed: "
          f"{len(res.layout.buildings)} | unplaced: {len(res.unplaced)}")
    print(f"  current roads: {s['current_roads']} | optimized roads: {s['optimized_roads']}"
          f" | tiles_saved: {s['tiles_saved']}")
    Path(args.out).write_text(render_comparison(current, res.layout), encoding="utf-8")
    print(f"Wrote before/after map to {args.out}")
    if res.unplaced:
        print(f"  WARNING: {len(res.unplaced)} buildings could not be placed "
              f"(city too dense for a full re-pack).")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foeopt")
    sub = parser.add_subparsers(dest="command", required=True)

    p_view = sub.add_parser("view", help="render current city to HTML")
    p_view.add_argument("city")
    p_view.add_argument("helper")
    p_view.add_argument("-o", "--out", default="city.html")
    p_view.set_defaults(func=_cmd_view)

    p_roads = sub.add_parser("roads", help="minimize roads with buildings fixed")
    p_roads.add_argument("city")
    p_roads.add_argument("helper")
    p_roads.add_argument("-o", "--out", default="roads.html")
    p_roads.add_argument("--diff", default=None)
    p_roads.set_defaults(func=_cmd_roads)

    p_layout = sub.add_parser("layout", help="re-pack the whole city to minimize roads")
    p_layout.add_argument("city")
    p_layout.add_argument("helper")
    p_layout.add_argument("-o", "--out", default="layout.html")
    p_layout.add_argument("--thorough", action="store_true",
                          help="sweep more configurations (slower, better)")
    p_layout.set_defaults(func=_cmd_layout)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
