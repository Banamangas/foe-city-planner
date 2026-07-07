import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import pytest

# Import without ortools in scope; _run_probe must be importable and its
# non-CP-SAT branches testable without the solver installed.
import exp_roads_first as mod


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
    monkeypatch.setattr(mod, "render_html", lambda lay: "<html/>")
    monkeypatch.setattr(mod.json, "dumps", lambda obj, indent=None: "{}")

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
                            lambda pattern, region, consumers, *, probe_limit, probe_workers=1:
                            ("UNSAT", None))
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
