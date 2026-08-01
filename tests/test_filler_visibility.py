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
