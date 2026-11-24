"""The PyInstaller spec bundles exactly the needed data files, never the repo
root (which holds player city files)."""
import ast
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "desktop" / "foe-city-planner.spec"

EXPECTED = {
    ("webapp/dist", "webapp/dist"),
    ("foeopt/data/catalog.json", "foeopt/data"),
    ("foeopt/data/catalog-manifest.json", "foeopt/data"),
    ("desktop/selftest_city.json", "desktop"),
}


def _datas() -> list[tuple[str, str]]:
    """The literal (source, dest) pairs of the spec's `DATAS = [...]`."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "DATAS"):
            return [tuple(e) for e in ast.literal_eval(node.value)]
    raise AssertionError("the spec has no literal DATAS list")


def test_spec_datas_are_exactly_the_four_files():
    assert set(_datas()) == EXPECTED
    assert len(_datas()) == len(EXPECTED)


def test_no_root_or_glob_source():
    for src, _ in _datas():
        assert src not in ("", ".", "./", "/", "..")
        assert "*" not in src and "?" not in src
        assert "/" in src, f"{src} sits at the repo root"


def test_manifest_is_bundled():
    assert any(src.endswith("catalog-manifest.json") for src, _ in _datas())


def test_spec_uses_datas_and_never_globs():
    text = SPEC.read_text(encoding="utf-8")
    assert "datas=_datas" in text.replace(" ", "")
    assert "glob" not in text
