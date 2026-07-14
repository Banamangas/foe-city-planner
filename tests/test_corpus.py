import json

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.corpus import CorpusWriter, load_manifest, load_instances, reconstruct


def _tiny_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 1, 1), True, 2, False, None, None, "hut")
    region = Region(frozenset((x, y) for x in range(5) for y in range(5)))
    return Layout(region, [th, c1], th, {})


def test_manifest_written_on_init(tmp_path):
    CorpusWriter(tmp_path, _tiny_layout()).close()
    man = load_manifest(tmp_path)
    assert isinstance(man["city_id"], str) and len(man["city_id"]) == 16
    assert [0, 0] in man["region"] and len(man["region"]) == 25
    assert man["buildings"] == [{"id": "10", "w": 1, "l": 1, "road_level": 2}]


def test_records_round_trip(tmp_path):
    w = CorpusWriter(tmp_path, _tiny_layout())
    th = Footprint(0, 0, 2, 2)
    w.record(k=9, roads=frozenset({(2, 1), (2, 0)}), th=th,
             status="SAT", secs=1.2, pos={10: (3, 0, 1, 1)})
    w.record(k=9, roads=frozenset({(2, 0)}), th=th,
             status="UNSAT", secs=0.4, pos=None)
    w.close()
    recs = list(load_instances(tmp_path))
    assert len(recs) == 2
    assert recs[0]["k"] == 9 and recs[0]["status"] == "SAT"
    assert recs[0]["roads"] == [[2, 0], [2, 1]]          # sorted
    assert recs[0]["th"] == [0, 0, 2, 2]
    assert recs[0]["pos"] == {"10": [3, 0, 1, 1]}        # keys stringified, tuples -> lists
    assert recs[1]["status"] == "UNSAT" and recs[1]["pos"] is None


def test_reconstruct(tmp_path):
    w = CorpusWriter(tmp_path, _tiny_layout())
    w.record(k=9, roads=frozenset({(2, 0), (2, 1)}), th=Footprint(0, 0, 2, 2),
             status="SAT", secs=1.0, pos={10: (3, 0, 1, 1)})
    w.close()
    man = load_manifest(tmp_path)
    rec = next(iter(load_instances(tmp_path)))
    out = reconstruct(man, rec)
    assert out["region"] == {(x, y) for x in range(5) for y in range(5)}
    assert out["skeleton"] == {(2, 0), (2, 1)}
    assert out["buildings"] == [{"id": "10", "w": 1, "l": 1, "road_level": 2}]
    assert out["th"] == (0, 0, 2, 2)
    assert out["status"] == "SAT" and out["pos"] == {"10": [3, 0, 1, 1]}


def test_load_instances_missing_file_is_empty(tmp_path):
    assert list(load_instances(tmp_path)) == []
