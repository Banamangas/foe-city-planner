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
    return Layout(Region(frozenset(region)), [th, c1], th, {}), region


def test_scorer_orders_and_prunes_patterns(monkeypatch):
    layout, region = _tiny()
    th = Footprint(0, 0, 2, 2)
    pa = rf.Pattern(th=th, roads=frozenset({(2, 0), (2, 1)}), params={"id": "a"})
    pb = rf.Pattern(th=th, roads=frozenset({(2, 0)}), params={"id": "b"})
    pc = rf.Pattern(th=th, roads=frozenset({(3, 0)}), params={"id": "c"})
    monkeypatch.setattr(rf, "generate_patterns", lambda *a, **k: [pa, pb, pc])
    monkeypatch.setattr(rf, "prefilter", lambda *a, **k: None)
    scores = {"a": 0.9, "b": 0.1, "c": 0.5}
    probed = []
    def fake_run_probe_seq(payload):
        pat = payload[0]
        probed.append(pat.params["id"])
        return {"k": payload[1], "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.0, "layout": None, "pat_index": 0, "pos": None}
    monkeypatch.setattr(rf, "_run_probe_seq", fake_run_probe_seq)
    params = SimpleNamespace(patterns=3, probe_limit=1.0, probe_workers=1,
                             deadline=time.monotonic() + 30, th_anchors="coarse")
    rf._probe_level(layout, set(region), layout.road_needing(), 5, random.Random(0),
                    params, lambda r: None, pool=None,
                    scorer=lambda p: scores[p.params["id"]], score_threshold=0.3)
    assert probed == ["a", "c"]        # ranked desc by score; "b" (0.1<0.3) pruned
