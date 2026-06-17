from __future__ import annotations

import argparse
import json
from pathlib import Path

from foeopt.build import build_layout
from foeopt.viz import render_html


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _cmd_view(args) -> int:
    layout = build_layout(_load(args.city), _load(args.helper))
    html = render_html(layout)
    Path(args.out).write_text(html)
    print(f"Wrote map to {args.out} ({len(layout.buildings)} buildings, "
          f"{len(layout.roads)} roads)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foeopt")
    sub = parser.add_subparsers(dest="command", required=True)

    p_view = sub.add_parser("view", help="render current city to HTML")
    p_view.add_argument("city")
    p_view.add_argument("helper")
    p_view.add_argument("-o", "--out", default="city.html")
    p_view.set_defaults(func=_cmd_view)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
