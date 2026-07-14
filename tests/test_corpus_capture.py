import random
import time
from types import SimpleNamespace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt import roads_first as rf


def _tiny():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 1, 1), True, 1, False, None, None, "hut")
    region = {(x, y) for x in range(5) for y in range(5)}
    layout = Layout(Region(frozenset(region)), [th, c1], th, {})
    pat = rf.Pattern(th=Footprint(0, 0, 2, 2),
                     roads=frozenset({(2, 0), (2, 1)}), params={"src": "test"})
    return layout, region, pat


def test_run_probe_includes_cp_sat_placement():
    layout, region, pat = _tiny()
    consumers = layout.road_needing()
    st, pos = rf.probe(pat, region, consumers, probe_limit=10.0, probe_workers=1)
    assert st == "SAT" and pos and 10 in pos
    res = rf._run_probe_seq((pat, 9, layout, 10.0, 1))
    assert "pos" in res
    assert res["pos"] == pos


def test_probe_level_records_each_probe(tmp_path, monkeypatch):
    from foeopt.corpus import CorpusWriter, load_instances
    layout, region, pat = _tiny()
    monkeypatch.setattr(rf, "generate_patterns", lambda *a, **k: [pat])
    monkeypatch.setattr(rf, "prefilter", lambda *a, **k: None)
    writer = CorpusWriter(tmp_path, layout)
    params = SimpleNamespace(patterns=1, probe_limit=10.0, probe_workers=1,
                             deadline=time.monotonic() + 30, th_anchors="coarse")
    rf._probe_level(layout, set(region), layout.road_needing(), 9,
                    random.Random(0), params, lambda r: None,
                    pool=None, corpus=writer)
    writer.close()
    recs = list(load_instances(tmp_path))
    assert len(recs) == 1
    assert recs[0]["k"] == 9
    assert recs[0]["roads"] == [[2, 0], [2, 1]]
    assert "pos" in recs[0]


def test_search_run_writes_manifest_and_instances(tmp_path):
    from foeopt.corpus import load_manifest, load_instances
    layout, _region, _pat = _tiny()
    rf.RoadsFirstSearch(layout, time_box=20.0, patterns=5, workers=1,
                        probe_workers=1, th_anchors="coarse",
                        corpus_dir=tmp_path).run()
    man = load_manifest(tmp_path)
    assert man["buildings"] == [{"id": "10", "w": 1, "l": 1, "road_level": 1}]
    for r in load_instances(tmp_path):        # every recorded line is well-formed
        assert set(r) >= {"k", "status", "secs", "th", "roads", "pos"}


def test_corpus_off_by_default_writes_nothing(tmp_path, monkeypatch):
    layout, _region, _pat = _tiny()
    monkeypatch.chdir(tmp_path)
    rf.RoadsFirstSearch(layout, time_box=20.0, patterns=5, workers=1,
                        probe_workers=1, th_anchors="coarse").run()
    assert not (tmp_path / "manifest.json").exists()
