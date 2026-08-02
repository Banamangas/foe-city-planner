import time
import pytest

# Import the real module under test, not the CLI wrapper. Tests that need
# CLI-specific behavior (arg parsing, --smoke) import exp_roads_first locally.
from foeopt import roads_first as mod


def test_run_probe_unsat_returns_status_no_layout():
    """A pattern that prefilter rejects fast (no anchors) -> UNSAT, no layout.
    _run_probe must return a dict with the documented keys, status UNSAT,
    achieved None, layout None, secs a float >= 0."""
    # Build a tiny layout where the consumer cannot sit on any road cell of
    # the pattern (1 consumer 2x2, pattern k=1 with a single road cell the
    # consumer's footprint cannot be adjacent to within a 1x1 region).
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 1, 1),
                  False, 1, True, None, None, "TH")
    consumer = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(2) for y in range(2)))
    lay = Layout(region, [th, consumer], th, {})
    # generate a real pattern at k=1 to feed _run_probe; the exact pattern
    # shape doesn't matter for this test — we just need _run_probe to run
    # the probe() path and return a well-formed dict. We mock probe via
    # monkeypatch to avoid needing ortools.
    import random
    pats = list(mod.generate_patterns(set(region.cells), 1, 1, 1, random.Random(0), 5))
    assert pats, "expected at least one pattern at k=1"
    pat = pats[0]
    # Monkeypatch probe to return UNSAT without calling CP-SAT.
    def fake_probe(pattern, region, consumers, *, probe_limit, **kwargs):
        return ("UNSAT", None)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "probe", fake_probe)
    # Set the worker globals as _worker_init would in the pool path.
    mod._WORKER_LAYOUT = lay
    mod._WORKER_PROBE_LIMIT = 30.0
    mod._WORKER_PROBE_WORKERS = 1
    try:
        result = mod._run_probe((pat, 1, 0))  # 3-tuple: pat, k, pat_index
    finally:
        monkeypatch.undo()
        mod._WORKER_LAYOUT = None
    assert set(result.keys()) >= {"k", "params", "status", "achieved", "secs", "layout"}
    assert result["status"] == "UNSAT"
    assert result["achieved"] is None
    assert result["layout"] is None
    assert isinstance(result["secs"], float)
    assert result["secs"] >= 0.0
    assert result["k"] == 1
    assert result["params"] == pat.params


def test_probe_level_sequential_fallback_matches_today():
    """With pool=None, _probe_level must behave exactly as today: patterns
    probed in generation order, results logged in order, best-achieved
    computed. Verify via a fake _run_probe that records call order."""
    import random
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    call_order = []
    from types import SimpleNamespace
    fake_layout = SimpleNamespace(roads=set(), buildings=[])
    def fake_run_probe(payload):
        pat, k, pat_index = payload  # 3-tuple (worker global carries layout)
        call_order.append(pat.params)
        if len(call_order) == 1:
            return {"k": k, "params": pat.params, "status": "SAT",
                    "achieved": k, "secs": 0.1,
                    "layout": fake_layout, "pat_index": pat_index}
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.1, "layout": None,
                "pat_index": pat_index}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "_run_probe", fake_run_probe)

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    log_rows = []
    def log(row):
        log_rows.append(row)

    region_set = set(region.cells)
    rng = random.Random(0)
    try:
        status, best = mod._probe_level(lay, region_set, [c1], 1, rng,
                                        FakeArgs, log, pool=None)
    finally:
        monkeypatch.undo()

    pats = list(mod.generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    expected_order = [p.params for p in pats if mod.prefilter(p, region_set, [c1]) is None]
    assert call_order == expected_order, (
        f"sequential fallback must probe in generation order; got {call_order} "
        f"expected {expected_order}")
    assert status == "FEASIBLE"
    assert best == 1
    assert any(r.get("status") == "SAT" for r in log_rows)


def test_probe_level_parallel_dispatch_completes_all(monkeypatch):
    """With a real Pool(2), _probe_level must dispatch all surviving patterns
    and collect every result (order may vary, set of statuses must match)."""
    pytest.importorskip("ortools")
    import random
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    log_rows = []
    def log(row):
        log_rows.append(row)

    region_set = set(region.cells)
    rng = random.Random(0)
    pool = mod.multiprocessing.Pool(
        2, initializer=mod._worker_init, initargs=(lay, 30.0, 1))
    try:
        status, best = mod._probe_level(lay, region_set, [c1], 1, rng,
                                        FakeArgs, log, pool=pool)
    finally:
        pool.close()
        pool.join()

    pats = list(mod.generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    surviving = [p for p in pats if mod.prefilter(p, region_set, [c1]) is None]
    probed = [r for r in log_rows if r.get("status") != "PREFILTERED"]
    assert len(probed) == len(surviving), (
        f"parallel dispatch must probe all {len(surviving)} surviving patterns, "
        f"got {len(probed)} log rows")


def test_run_probe_payload_uses_worker_global_not_embedded_layout(monkeypatch):
    """_run_probe must accept the 3-tuple (pat, k, pat_index) and read layout
    from the worker global, not from the payload. Verify by setting the
    global in-process and calling _run_probe with a 3-tuple."""
    import random
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    # Set the worker global as the initializer would.
    mod._WORKER_LAYOUT = lay
    mod._WORKER_PROBE_LIMIT = 30.0
    mod._WORKER_PROBE_WORKERS = 1
    try:
        pats = list(mod.generate_patterns(set(region.cells), 2, 2, 1, random.Random(0), 5))
        pat = next(p for p in pats if mod.prefilter(p, set(region.cells), [c1]) is None)
        # Fake probe so we don't need ortools.
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(mod, "probe",
                            lambda pattern, region, consumers, *, probe_limit, probe_workers=1,
                            symmetry_breaking=False, hints=None,
                            stub_priority=False, solver_overrides=None: ("UNSAT", None))
        try:
            result = mod._run_probe((pat, 1, 0))  # 3-tuple: pat, k, pat_index
        finally:
            monkeypatch.undo()
        assert result["pat_index"] == 0
        assert result["k"] == 1
    finally:
        del mod._WORKER_LAYOUT
        del mod._WORKER_PROBE_LIMIT
        del mod._WORKER_PROBE_WORKERS


def test_k_start_auto_resolves_to_pick_k_start_value(monkeypatch):
    """k_start='auto' should resolve to pick_k_start(layout) inside
    RoadsFirstSearch.run, not stay as the string 'auto' (which would crash the
    k-walk's integer arithmetic). Verify by capturing the k the first level()
    call probes."""
    from foeopt.loader import load_layout
    from foeopt.bounds import pick_k_start

    import pathlib
    if not pathlib.Path("darkzig.json").exists():
        pytest.skip("darkzig.json not present")
    lay = load_layout("darkzig.json")  # assumes cwd is repo root

    captured_k = []
    def spy_probe_level(layout, region, consumers, k, rng, args, log, pool=None,
                        on_improvement=None, corpus=None, scorer=None,
                        score_threshold=None, **_kw):
        captured_k.append(k)
        return ("FEASIBLE", 200)  # short-circuit: one level, then walk stops

    monkeypatch.setattr(mod, "_probe_level", spy_probe_level)
    search = mod.RoadsFirstSearch(
        lay, time_box=1.0, patterns=5, probe_limit=30.0,
        workers=1, probe_workers=1, th_anchors="coarse", k_start="auto")
    try:
        search.run()
    except Exception:
        pass  # run may error on the short-circuit; we only care about captured_k
    monkeypatch.undo()
    expected = pick_k_start(lay)
    assert captured_k, "run did not probe any level"
    assert captured_k[0] == expected, (
        f"k_start='auto' should probe k={expected} first (pick_k_start), "
        f"got k={captured_k[0]}")


def test_k_start_explicit_integer_overrides_auto(monkeypatch):
    """k_start=152 (explicit integer) must use 152 exactly, not pick_k_start."""
    from foeopt.loader import load_layout
    import pathlib

    if not pathlib.Path("darkzig.json").exists():
        pytest.skip("darkzig.json not present")
    lay = load_layout("darkzig.json")

    captured_k = []
    def spy_probe_level(layout, region, consumers, k, rng, args, log, pool=None,
                        on_improvement=None, corpus=None, scorer=None,
                        score_threshold=None, **_kw):
        captured_k.append(k)
        return ("FEASIBLE", 200)
    monkeypatch.setattr(mod, "_probe_level", spy_probe_level)
    search = mod.RoadsFirstSearch(
        lay, time_box=1.0, patterns=5, probe_limit=30.0,
        workers=1, probe_workers=1, th_anchors="coarse", k_start=152)
    try:
        search.run()
    except Exception:
        pass
    monkeypatch.undo()
    assert captured_k, "run did not probe any level"
    assert captured_k[0] == 152, f"explicit k_start=152 ignored, got {captured_k[0]}"


def test_fallback_cap_is_k_max_not_168(monkeypatch):
    """When k_start is infeasible, the upward fallback must walk up to k_max
    (city-specific area ceiling), not the hardcoded 168. Verify on the user's
    city (k_max=145): an infeasible k_start=145 should let the fallback try
    145+4=149 only if 149 <= k_max=145 (it isn't) -> fallback stops at 145,
    FAMILY_TOO_WEAK. If the cap were still 168, the fallback would try
    149,153,...,169 (all area-infeasible above 145) before giving up."""
    from foeopt.loader import load_layout
    import pathlib

    helper = pathlib.Path("city-user-data-foe-helper.json")
    if not (pathlib.Path("city-user-data.json").exists() and helper.exists()):
        pytest.skip("user city files not present")
    lay = load_layout("city-user-data.json", str(helper))
    k_max = len(lay.region.cells) - sum(b.footprint.width * b.footprint.length
                                        for b in lay.buildings)
    assert k_max == 145  # sanity: the user city's area ceiling

    probed_ks = []
    def spy_probe_level(layout, region, consumers, k, rng, args, log, pool=None,
                        on_improvement=None, corpus=None, scorer=None,
                        score_threshold=None, **_kw):
        probed_ks.append(k)
        return ("INFEASIBLE", None)  # every level infeasible -> fallback climbs
    monkeypatch.setattr(mod, "_probe_level", spy_probe_level)
    search = mod.RoadsFirstSearch(
        lay, time_box=60.0, patterns=5, probe_limit=30.0,
        workers=1, probe_workers=1, th_anchors="coarse", k_start=145)
    try:
        result = search.run()
    except Exception:
        result = None
    monkeypatch.undo()
    # The fallback must NOT probe above k_max=145. If the cap were 168,
    # probed_ks would contain 149, 153, ... up to 168.
    above_kmax = [k for k in probed_ks if k > k_max]
    assert not above_kmax, (
        f"fallback probed above k_max={k_max}: {above_kmax} (cap not respected)")


def test_smoke_does_not_override_k_start(monkeypatch):
    """--smoke must NOT override k_start to 156; it should leave --k-start auto
    (the default) so RoadsFirstSearch resolves it to pick_k_start(layout).
    Verify by spying on RoadsFirstSearch.__init__ to capture the kwargs main()
    passes, and stubbing .run() to short-circuit."""
    import pathlib
    if not pathlib.Path("darkzig.json").exists():
        pytest.skip("darkzig.json not present")

    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import exp_roads_first as cli

    captured_kwargs = []
    real_init = cli.RoadsFirstSearch.__init__
    def spy_init(self, *a, **kw):
        captured_kwargs.append(kw)
    monkeypatch.setattr(cli.RoadsFirstSearch, "__init__", spy_init)
    def fake_run(self, on_improvement=None, on_status=None, should_stop=None):
        return {"verdict": "DONE", "results": {}}
    monkeypatch.setattr(cli.RoadsFirstSearch, "run", fake_run)
    try:
        cli.main(["darkzig.json", "--smoke"])
    except Exception:
        pass
    monkeypatch.undo()
    assert captured_kwargs, "main() did not create RoadsFirstSearch"
    kw = captured_kwargs[0]
    assert kw["k_start"] == "auto", (
        f"--smoke overrode k_start to {kw['k_start']!r}; expected 'auto' (the default)")
    # Also confirm the other smoke overrides still apply.
    assert kw["workers"] == 1
    assert kw["probe_workers"] == 1
    assert kw["patterns"] == 20
    assert kw["probe_limit"] == 20.0
    assert kw["time_box"] == 600.0
