import pytest

from foeopt.cli import main

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def _require(name):
    p = REPO / name
    if not p.exists():
        pytest.skip(f"{name} not present (large data file, gitignored)")
    return p


def test_view_accepts_single_combined_file(tmp_path):
    out = tmp_path / "map.html"
    rc = main(["view", str(_require("darkzig.json")), "-o", str(out)])
    assert rc == 0
    assert out.exists()
    assert out.read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")


def test_roads_accepts_two_file_split(tmp_path):
    out = tmp_path / "roads.html"
    rc = main(["roads", str(REPO / "city-user-data.json"),
               str(_require("city-user-data-foe-helper.json")), "-o", str(out)])
    assert rc == 0
    assert out.exists()
