import pytest

from foeopt.build import build_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
from foeopt.validate import is_valid


def test_layout_cli_accepts_budget_and_seed():
    from foeopt.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["layout", "city.json", "--budget", "0.2", "--seed", "3"])
    assert args.budget == 0.2
    assert args.seed == 3
    assert args.thorough is False


def test_layout_reports_road_estimate(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    est = road_estimate(current)
    assert isinstance(est, int) and est >= 0


def test_repack_real_city_is_valid_or_reports_unplaced(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    res = repack(current, budget_seconds=0.3)
    # Correctness invariant: never an overlapping / out-of-region layout.
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= current.region.cells
        assert not (cells & occ)
        occ |= cells
    if not res.unplaced:
        # if everything was placed, it must be valid and not worse than current
        assert is_valid(res.layout)
        assert len(res.layout.roads) <= len(current.roads)
    else:
        # otherwise the shortfall is reported explicitly (expected at 96.6% density)
        assert len(res.unplaced) > 0


def test_layout_cli_accepts_polish_flags():
    from foeopt.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["layout", "city.json", "--polish", "--anneal-budget", "0.2"])
    assert args.polish is True
    assert args.anneal_budget == 0.2


def test_layout_cli_accepts_lns_flag():
    from foeopt.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["layout", "city.json", "--lns", "2"])
    assert args.lns == 2.0


def test_layout_lns_writes_comparison_html(tmp_path, monkeypatch, repo_root):
    """--lns runs the corridor-LNS pass and writes a before/after HTML under
    output/lns/<city-stem>-<timestamp>.html. This real fixture sits at ~96.6%
    density (see test_repack_real_city_is_valid_or_reports_unplaced above), so
    a small test budget can legitimately leave buildings unplaced (rc == 1);
    that's an expected outcome here, not a test failure -- the thing under
    test is that the comparison HTML gets written regardless."""
    from foeopt.cli import main
    helper = repo_root / "city-user-data-foe-helper.json"
    if not helper.exists():
        pytest.skip("city-user-data-foe-helper.json not present")
    monkeypatch.chdir(tmp_path)  # output/lns lands under tmp_path
    rc = main(["layout", str(repo_root / "city-user-data.json"),
               str(helper),
               "--budget", "2", "--anneal-budget", "1", "--lns", "2",
               "-o", str(tmp_path / "layout.html")])
    assert rc in (0, 1)
    out_dir = tmp_path / "output" / "lns"
    files = list(out_dir.glob("*.html"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "before" in text.lower() and "after" in text.lower()
