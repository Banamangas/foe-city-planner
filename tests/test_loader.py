import json
from foeopt.loader import read_json


def test_read_json_plain(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text(json.dumps({"a": 1, "b": [2, 3]}), encoding="utf-8")
    assert read_json(str(p)) == {"a": 1, "b": [2, 3]}


def test_read_json_with_bom(tmp_path):
    p = tmp_path / "bom.json"
    # write a UTF-8 BOM followed by JSON
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"x": 5}).encode("utf-8"))
    assert read_json(str(p)) == {"x": 5}
