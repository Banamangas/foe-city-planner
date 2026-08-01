"""A run that dies at the filler stage must say so.

Before this, CP-SAT could place every road-needing building, the leftover
"filler" buildings could then fail to fit, and the user saw a run that "found
nothing" with no explanation. `_place_fillers` never exits early, so the real
"placed N of M" was already computed and thrown away.
"""
from foeopt.roads_first import new_filler_stats, summarise_fillers


def _stats(rows):
    """rows: (placed, total, unplaced_names)"""
    fs = new_filler_stats()
    for placed, total, names in rows:
        fs["failures"] += 1
        fs["placed"] += placed
        fs["total"] += total
        fs["worst"] = placed if fs["worst"] is None else min(fs["worst"], placed)
        for n in names:
            fs["by_building"][n] = fs["by_building"].get(n, 0) + 1
    return fs


def test_no_failures_reports_nothing():
    assert summarise_fillers(new_filler_stats()) is None
    assert summarise_fillers({}) is None


def test_reports_placed_of_total_not_a_bare_failure():
    s = summarise_fillers(_stats([(30, 32, ["A", "B"]), (28, 32, ["A"])]))
    assert s["failures"] == 2
    assert s["mean_placed"] == 29.0
    assert s["mean_total"] == 32.0


def test_worst_case_is_the_minimum_not_the_last():
    s = summarise_fillers(_stats([(31, 32, []), (12, 32, []), (30, 32, [])]))
    assert s["worst_placed"] == 12


def test_names_the_repeat_offenders_most_frequent_first():
    s = summarise_fillers(_stats([
        (30, 32, ["Cathedral", "Manor"]),
        (29, 32, ["Cathedral"]),
        (28, 32, ["Cathedral", "Barn"]),
    ]))
    names = [u["name"] for u in s["top_unplaced"]]
    assert names[0] == "Cathedral"
    assert s["top_unplaced"][0]["times"] == 3
    assert set(names) == {"Cathedral", "Manor", "Barn"}


def test_offender_list_is_capped_so_the_ui_stays_readable():
    s = summarise_fillers(_stats([(0, 20, [f"b{i}" for i in range(40)])]))
    assert len(s["top_unplaced"]) == 5


def test_run_result_carries_the_summary_key():
    """The webapp reads the whole run dict straight from the done event, so the
    key must exist even on a run where nothing failed this way."""
    import inspect
    from foeopt.roads_first import RoadsFirstSearch
    src = inspect.getsource(RoadsFirstSearch.run)
    assert '"filler_failures"' in src


def test_the_walk_actually_accumulates_filler_failures(monkeypatch):
    """The link that stochastic search cannot be relied on to exercise: a
    SAT_FILLER_FAIL probe row must land in the run's tally, not be dropped."""
    from types import SimpleNamespace
    import foeopt.roads_first as rf
    from foeopt.loader import load_layout

    lay = load_layout('CityMap-Born-FR16-2026-07-07.json')
    region = set(lay.region.cells)
    consumers = lay.road_needing()

    def fake_seq(payload):
        pat = payload[0]
        return {"k": payload[1], "params": pat.params, "status": "SAT_FILLER_FAIL",
                "achieved": None, "secs": 0.1, "layout": None, "pat_index": 0,
                "pos": None,
                "filler": {"fillers_total": 32, "fillers_placed": 29,
                           "unplaced": ["Cathedral", "Manor", "Barn"],
                           "repair_ran": True}}

    monkeypatch.setattr(rf, "_run_probe_seq", fake_seq)
    stats = rf.new_filler_stats()
    params = SimpleNamespace(patterns=6, probe_limit=1.0, probe_workers=1,
                             deadline=float("inf"), th_anchors="coarse",
                             pattern_family="comb")
    rf._probe_levels_batch(lay, region, consumers, [96], __import__("random").Random(0),
                           params, lambda r: None, pool=None, filler_stats=stats)

    assert stats["failures"] > 0, "SAT_FILLER_FAIL rows were dropped"
    summary = rf.summarise_fillers(stats)
    assert summary["mean_placed"] == 29.0
    assert summary["mean_total"] == 32.0
    assert summary["worst_placed"] == 29
    assert summary["top_unplaced"][0]["name"] in {"Cathedral", "Manor", "Barn"}
