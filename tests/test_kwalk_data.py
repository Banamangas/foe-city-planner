import numpy as np

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.corpus import CorpusWriter
from rl.kwalk_data import build_samples, encode_instance, LABEL_NEG


def _layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {})


def _corpus(tmp_path):
    w = CorpusWriter(tmp_path, _layout())
    th = Footprint(0, 0, 2, 2)
    w.record(k=5, roads=frozenset({(2, 0), (2, 1)}), th=th, status="SAT", secs=1.0,
             pos={10: (3, 0, 2, 2)})
    w.record(k=5, roads=frozenset({(2, 0)}), th=th, status="UNSAT", secs=0.2, pos=None)
    w.record(k=4, roads=frozenset({(2, 0)}), th=th, status="UNKNOWN", secs=8.0, pos=None)
    w.record(k=5, roads=frozenset({(2, 0), (2, 1)}), th=th, status="SAT_ROTATED", secs=1.0,
             pos={10: (3, 0, 2, 2)})
    w.close()
    return tmp_path


def test_build_samples_labels_and_excludes_unknown(tmp_path):
    ds = build_samples([_corpus(tmp_path)])
    assert ds["y"].tolist() == [1, 0, 0]          # SAT=1, UNSAT=0, SAT_ROTATED=0; UNKNOWN dropped
    assert ds["X"].shape == (3, 4, ds["H"], ds["W"])
    assert ds["g"].shape[0] == 3
    assert "SAT_ROTATED" in LABEL_NEG


def test_encode_channels(tmp_path):
    from foeopt.corpus import load_manifest, load_instances
    d = _corpus(tmp_path)
    man = load_manifest(d)
    rec = next(r for r in load_instances(d) if r["status"] == "SAT")
    grid, glob = encode_instance(man, rec, 6, 6)
    assert grid.shape == (4, 6, 6)
    assert grid[0].sum() == 36                     # region: full 6x6
    assert grid[1, 0, 2] == 1 and grid[1, 1, 2] == 1   # skeleton roads at (2,0),(2,1)
    assert grid[2, 0, 0] == 1 and grid[2, 1, 1] == 1   # TH footprint 2x2 at (0,0)
    assert grid[3, 0, 3] == 1                       # skeleton-adjacency: (3,0) is ortho-adjacent to road (2,0)
    assert glob.ndim == 1 and glob.shape[0] >= 4
