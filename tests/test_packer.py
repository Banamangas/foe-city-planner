from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packer import PackConfig, PackResult, classify, bbox


def _b(eid, x, y, w, l, needs=False, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic", Footprint(x, y, w, l),
                    needs_road=needs, road_level=1, is_townhall=th,
                    set_id=None, chain_id=None, name=f"b{eid}")


def test_classify_splits_townhall_consumers_fillers():
    th = _b(1, 0, 0, 1, 1, th=True)
    cons = _b(2, 2, 0, 1, 1, needs=True)
    fill = _b(3, 4, 0, 1, 1, needs=False)
    layout = Layout(Region(frozenset()), [th, cons, fill], th)
    t, consumers, fillers = classify(layout)
    assert t is th
    assert consumers == [cons]
    assert fillers == [fill]


def test_bbox_from_region():
    region = Region(frozenset({(0, 0), (3, 0), (0, 2)}))
    assert bbox(region) == (4, 3)


def test_packconfig_and_packresult_construct():
    cfg = PackConfig(orientation="h", spacing=4, trunk_x=0)
    assert cfg.spacing == 4
    res = PackResult(layout=Layout(Region(frozenset()), [], None), unplaced=[])
    assert res.unplaced == []
