import sys, pathlib
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
    try:
        result = mod._run_probe((pat, 1, lay, 30.0, 1))
    finally:
        monkeypatch.undo()
    assert set(result.keys()) >= {"k", "params", "status", "achieved", "secs", "layout"}
    assert result["status"] == "UNSAT"
    assert result["achieved"] is None
    assert result["layout"] is None
    assert isinstance(result["secs"], float)
    assert result["secs"] >= 0.0
    assert result["k"] == 1
    assert result["params"] == pat.params
