from foeopt.cli import main

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def test_view_accepts_single_combined_file(tmp_path):
    out = tmp_path / "map.html"
    rc = main(["view", str(REPO / "darkzig.json"), "-o", str(out)])
    assert rc == 0
    assert out.exists()
    assert out.read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")


def test_roads_accepts_two_file_split(tmp_path):
    out = tmp_path / "roads.html"
    rc = main(["roads", str(REPO / "city-user-data.json"),
               str(REPO / "city-user-data-foe-helper.json"), "-o", str(out)])
    assert rc == 0
    assert out.exists()
