import gzip
import hashlib
import json
import pathlib
import subprocess
import sys

from foeopt.catalog_build import build, canonical_bytes, manifest, sanity

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "update_catalog.py"


def old_style(cid="W_A", name="Old", type_="main_building", w=3, l=4):
    return {"id": cid, "name": name, "type": type_, "width": w, "length": l,
            "requirements": {"street_connection_level": 1}}


def comp_style(cid="C_B", name="Comp", type_="decoration", size=(2, 2)):
    return {"id": cid, "name": name, "type": type_,
            "components": {"AllAge": {
                "placement": {"size": {"x": size[0], "y": size[1]}, "other": 1},
                "streetConnectionRequirement": {"requiredLevel": 2}}}}


def test_new_size_wins_and_previous_only_kept():
    prev = {"W_A": {"id": "W_A", "name": "Old", "type": "x", "width": 1, "length": 1},
            "GONE": {"id": "GONE", "name": "Gone", "width": 2, "length": 2}}
    out = build([old_style(w=3, l=4)], prev)
    assert (out["W_A"]["width"], out["W_A"]["length"]) == (3, 4)
    assert out["GONE"] == prev["GONE"]


def test_components_entry_slimmed():
    out = build([comp_style()], {})
    comp = out["C_B"]["components"]["AllAge"]
    assert comp["placement"] == {"size": {"x": 2, "y": 2}}
    assert comp["streetConnectionRequirement"] == {"requiredLevel": 2}


def test_empty_new_type_keeps_previous():
    prev = {"W_A": {"id": "W_A", "name": "Old", "type": "main_building",
                    "width": 1, "length": 1}}
    assert build([old_style(type_="")], prev)["W_A"]["type"] == "main_building"
    assert build([old_style(type_="street")], prev)["W_A"]["type"] == "street"


def test_names_from_names_file_win():
    prev = {"W_A": {"id": "W_A", "name": "Ancien", "width": 1, "length": 1}}
    out = build([old_style(name="Eng")], prev, {"W_A": {"en": "E", "fr": "F"}})
    assert out["W_A"]["names"] == {"en": "E", "fr": "F"}
    assert out["W_A"]["name"] == "F"


def test_names_fall_back_to_previous_fr_and_lookup_en():
    prev = {"W_A": {"id": "W_A", "name": "Ancien", "width": 1, "length": 1}}
    out = build([old_style(name="Eng")], prev)
    assert out["W_A"]["names"] == {"en": "Eng", "fr": "Ancien"}
    assert out["W_A"]["name"] == "Ancien"


def test_names_untouched_when_nothing_differs_or_no_previous():
    prev = {"W_A": {"id": "W_A", "name": "Same", "width": 1, "length": 1}}
    assert "names" not in build([old_style(name="Same")], prev)["W_A"]
    out = build([old_style(name="Fresh")], {})
    assert "names" not in out["W_A"] and out["W_A"]["name"] == "Fresh"


def test_sanity_flags_dropped_id_and_zero_size():
    prev = {"A": old_style("A"), "B": old_style("B")}
    probs = sanity({"A": old_style("A")}, prev)
    assert any("B" in p for p in probs)
    bad = {"A": old_style("A", w=0, l=0), "B": old_style("B")}
    assert any("A" in p for p in sanity(bad, prev))
    assert sanity(dict(prev), prev) == []


def test_manifest_sha_matches_canonical_bytes():
    cat = {"B": old_style("B"), "A": old_style("A")}
    m = manifest(cat, "v1")
    assert m["sha256"] == hashlib.sha256(
        json.dumps(cat, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert (m["schema"], m["count"], m["source_version"]) == (1, 2, "v1")
    assert m["built_at"].endswith("Z")
    assert canonical_bytes(cat).startswith(b'{"A":')


def _run(tmp_path, lookup, prev, prev_name="prev.json"):
    (tmp_path / "lookup.json").write_text(json.dumps(lookup))
    pp = tmp_path / prev_name
    if prev_name.endswith(".gz"):
        pp.write_bytes(gzip.compress(json.dumps(prev).encode()))
    else:
        pp.write_text(json.dumps(prev))
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(CLI), "--lookup", str(tmp_path / "lookup.json"),
                        "--previous", str(pp), "--out", str(out),
                        "--source-version", "v9"],
                       capture_output=True, text=True, cwd=ROOT)
    return r, out


def test_cli_writes_three_files(tmp_path):
    r, out = _run(tmp_path, [old_style("A"), comp_style("C")],
                  {"A": old_style("A")}, "prev.json.gz")
    assert r.returncode == 0, r.stderr
    data = (out / "catalog.json").read_bytes()
    assert gzip.decompress((out / "catalog.json.gz").read_bytes()) == data
    m = json.loads((out / "catalog-manifest.json").read_text())
    assert m["sha256"] == hashlib.sha256(data).hexdigest()
    assert m["count"] == 2 and m["source_version"] == "v9"
    assert set(json.loads(data)) == {"A", "C"}


def test_cli_sanity_failure_exits_1_and_writes_nothing(tmp_path):
    r, out = _run(tmp_path, [old_style("A", w=0, l=0)], {"A": old_style("A")})
    assert r.returncode == 1
    assert not out.exists() or list(out.iterdir()) == []


def test_en_only_names_entry_keeps_previous_french():
    prev = {"W_A": {"id": "W_A", "name": "Ancien", "names": {"en": "O", "fr": "Ancien"},
                    "width": 1, "length": 1}}
    out = build([old_style(name="Eng")], prev, {"W_A": {"en": "X"}})
    assert out["W_A"]["names"] == {"en": "X", "fr": "Ancien"}
    assert out["W_A"]["name"] == "Ancien"


def test_rebuilding_from_own_output_is_idempotent():
    prev = {"W_A": {"id": "W_A", "name": "Ancien", "width": 1, "length": 1}}
    names = {"W_A": {"en": "X"}}
    first = build([old_style(name="Eng")], prev, names)
    assert build([old_style(name="Eng")], first, names) == first
    assert build([old_style(name="Eng")], first) == build([old_style(name="Eng")], prev)


def test_cli_with_names(tmp_path):
    (tmp_path / "names.json").write_text(json.dumps({"A": {"en": "E"}}))
    (tmp_path / "lookup.json").write_text(json.dumps([old_style("A", name="Eng")]))
    prev = {"A": {"id": "A", "name": "Ancien", "width": 1, "length": 1}}
    (tmp_path / "prev.json").write_text(json.dumps(prev))
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(CLI), "--lookup", str(tmp_path / "lookup.json"),
                        "--names", str(tmp_path / "names.json"),
                        "--previous", str(tmp_path / "prev.json"), "--out", str(out)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    entry = json.loads((out / "catalog.json").read_text())["A"]
    assert entry["names"] == {"en": "E", "fr": "Ancien"} and entry["name"] == "Ancien"
