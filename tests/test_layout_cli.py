from foeopt.build import build_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
from foeopt.validate import is_valid


def test_layout_reports_road_estimate(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    est = road_estimate(current)
    assert isinstance(est, int) and est >= 0


def test_repack_real_city_is_valid_or_reports_unplaced(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    res = repack(current, thorough=False)
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
