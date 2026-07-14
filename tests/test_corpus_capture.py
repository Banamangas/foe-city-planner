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
