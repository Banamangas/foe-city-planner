"""Advanced run parameters: webapp/params.py coercion, the /api/options spec
endpoint, the /api/optimize passthrough, and JobManager forwarding into
RoadsFirstSearch. No solver runs here -- RoadsFirstSearch is faked -- so these
are fast and deterministic."""
import time

import pytest

from foeopt.model import Building, Footprint, Layout, Region
from webapp.params import (
    DEFAULTS, OPTION_SPECS, SMOKE_PRESET, OptionError, parse_options,
)

flask = pytest.importorskip("flask")
from webapp.app import create_app  # noqa: E402


def _tiny_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    region = Region(frozenset((x, y) for x in range(4) for y in range(4)))
    return Layout(region, [th], th, {})


# ---------------------------------------------------------------- parse_options

def test_empty_body_yields_every_default():
    assert parse_options({}) == DEFAULTS
    # the webapp defaults deliberately differ from the CLI's (lessons 2026-07-19/21)
    assert DEFAULTS["workers"] == 6 and DEFAULTS["probe_workers"] == 2
    assert DEFAULTS["concurrent_levels"] == 4 and DEFAULTS["th_anchors"] == "full"


def test_unknown_keys_are_ignored_and_do_not_leak_into_kwargs():
    opts = parse_options({"city_id": "abc", "nonsense": 1})
    assert "city_id" not in opts and "nonsense" not in opts
    assert set(opts) == set(DEFAULTS)


def test_every_spec_maps_to_a_jobmanager_submit_keyword():
    """params.py is only a single source of truth if submit() accepts all of it."""
    import inspect
    from webapp.runner import JobManager
    accepted = set(inspect.signature(JobManager.submit).parameters) - {"self", "layout"}
    assert {s["name"] for s in OPTION_SPECS} <= accepted


def test_numeric_strings_are_coerced():
    opts = parse_options({"patterns": "700", "probe_limit": "300", "workers": 8})
    assert opts["patterns"] == 700 and isinstance(opts["patterns"], int)
    assert opts["probe_limit"] == 300.0 and isinstance(opts["probe_limit"], float)
    assert opts["workers"] == 8


def test_k_start_accepts_auto_or_an_int():
    assert parse_options({"k_start": "auto"})["k_start"] == "auto"
    assert parse_options({"k_start": "105"})["k_start"] == 105
    assert parse_options({"k_start": 105})["k_start"] == 105


def test_lane_cap_blank_means_none_but_blank_elsewhere_means_default():
    assert parse_options({"lane_cap": ""})["lane_cap"] is None
    assert parse_options({"lane_cap": None})["lane_cap"] is None
    assert parse_options({"lane_cap": "12"})["lane_cap"] == 12
    # a cleared non-nullable field falls back rather than exploding
    assert parse_options({"patterns": ""})["patterns"] == DEFAULTS["patterns"]


def test_bools_accept_json_and_string_forms():
    assert parse_options({"warm_start": True})["warm_start"] is True
    assert parse_options({"warm_start": "true"})["warm_start"] is True
    assert parse_options({"stub_priority": "false"})["stub_priority"] is False


@pytest.mark.parametrize("body, needle", [
    ({"workers": 0}, "must be >= 1"),
    ({"workers": 999}, "must be <= 64"),
    ({"patterns": "many"}, "expected an integer"),
    ({"th_anchors": "sideways"}, "must be one of"),
    ({"pattern_family": "spiral"}, "must be one of"),
    ({"k_start": "later"}, "expected an integer"),
    ({"symmetry_breaking": "yes"}, "expected a boolean"),
])
def test_out_of_range_and_mistyped_values_raise(body, needle):
    with pytest.raises(OptionError) as exc:
        parse_options(body)
    assert needle in str(exc.value)


def test_smoke_preset_is_a_valid_option_set():
    opts = parse_options(dict(SMOKE_PRESET))
    assert opts["patterns"] == 20 and opts["workers"] == 1
    assert opts["probe_limit"] == 20.0 and opts["time_box"] == 600.0


# ---------------------------------------------------------------- endpoints

@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def test_api_options_describes_every_parameter(client):
    body = client.get("/api/options").get_json()
    names = {o["name"] for o in body["options"]}
    assert names == set(DEFAULTS)
    for opt in body["options"]:
        assert opt["label"] and opt["help"] and opt["type"] and opt["cli"]
        assert opt["group"] in body["groups"]
    assert body["presets"]["smoke"] == SMOKE_PRESET


@pytest.fixture()
def stub_city(monkeypatch):
    """A client plus a cached city_id, with the loader stubbed so the test does
    not need one of the gitignored game dumps."""
    import webapp.app as app_mod
    monkeypatch.setattr(app_mod, "load_layout_from_dict", lambda payload: _tiny_layout())
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    client = app.test_client()
    city_id = client.post("/api/load", json={"stub": True}).get_json()["city_id"]
    return client, city_id


def test_optimize_forwards_all_options_and_echoes_them(stub_city, monkeypatch):
    import webapp.app as app_mod
    client, city_id = stub_city
    captured = {}
    monkeypatch.setattr(app_mod.JobManager, "submit",
                        lambda self, layout, **kw: captured.update(kw) or "job1")

    r = client.post("/api/optimize", json={
        "city_id": city_id, "patterns": 700, "pattern_family": "lane",
        "lane_cap": "", "stub_priority": True, "k_start": "105",
    })
    assert r.status_code == 200
    assert captured["patterns"] == 700
    assert captured["pattern_family"] == "lane"
    assert captured["lane_cap"] is None
    assert captured["stub_priority"] is True
    assert captured["k_start"] == 105
    assert captured["workers"] == DEFAULTS["workers"]  # untouched knobs keep defaults
    assert r.get_json()["options"]["patterns"] == 700


def test_optimize_rejects_a_bad_option_with_400_and_starts_nothing(stub_city, monkeypatch):
    import webapp.app as app_mod
    client, city_id = stub_city
    called = []
    monkeypatch.setattr(app_mod.JobManager, "submit",
                        lambda self, layout, **kw: called.append(kw) or "job1")

    r = client.post("/api/optimize", json={"city_id": city_id, "workers": 999})
    assert r.status_code == 400
    assert "must be <= 64" in r.get_json()["error"]
    assert called == []


# ---------------------------------------------------------------- runner

def _submit_and_capture(monkeypatch, **kwargs):
    import webapp.runner as runner
    captured = {}

    class FakeSearch:
        def __init__(self, layout, **kw):
            captured.update(kw)

        def run(self, **kw):
            return {"verdict": "DONE"}

    monkeypatch.setattr(runner, "RoadsFirstSearch", FakeSearch)
    jm = runner.JobManager()
    jm.submit(_tiny_layout(), **kwargs)
    for _ in range(100):
        if captured:
            break
        time.sleep(0.02)
    return captured


def test_submit_threads_advanced_params_into_the_search(monkeypatch):
    captured = _submit_and_capture(
        monkeypatch, time_box=0.1, pattern_family="lane", lane_cap=9,
        stub_priority=True, symmetry_breaking=True)
    assert captured["pattern_family"] == "lane"
    assert captured["lane_cap"] == 9
    assert captured["stub_priority"] is True
    assert captured["symmetry_breaking"] is True
    assert captured["hint_layout"] is None  # warm start off => no hints


def test_warm_start_repacks_and_passes_a_hint_layout(monkeypatch):
    import foeopt.packer as packer
    hinted = _tiny_layout()
    calls = []

    class FakeResult:
        layout = hinted

    monkeypatch.setattr(packer, "repack",
                        lambda layout, **kw: calls.append(kw) or FakeResult())
    # A box with room for it: the requested budget is honoured verbatim.
    captured = _submit_and_capture(monkeypatch, time_box=60.0, warm_start=True,
                                   warm_start_budget=7.0)
    assert captured["hint_layout"] is hinted
    assert calls == [{"budget_seconds": 7.0}]
    # ...and the search gets the REST of the box, not the whole thing: the warm
    # start used to run entirely outside it (a 60s request took 90s).
    assert captured["time_box"] <= 60.0


def test_warm_start_budget_is_capped_by_the_time_box(monkeypatch):
    """A warm start must never eat the box it is supposed to accelerate.
    Capped at half, so a 0.1s box cannot spend 7s repacking."""
    import foeopt.packer as packer
    hinted = _tiny_layout()
    calls = []

    class FakeResult:
        layout = hinted

    monkeypatch.setattr(packer, "repack",
                        lambda layout, **kw: calls.append(kw) or FakeResult())
    _submit_and_capture(monkeypatch, time_box=0.1, warm_start=True,
                        warm_start_budget=7.0)
    assert calls[0]["budget_seconds"] < 7.0, "budget must be capped for a tiny box"
    assert calls[0]["budget_seconds"] <= max(1.0, 0.1 * 0.5)
