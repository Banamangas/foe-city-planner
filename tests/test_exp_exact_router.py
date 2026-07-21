import importlib.util, pathlib
from foeopt.model import Building, Footprint, Layout, Region

_spec = importlib.util.spec_from_file_location(
    "exp_exact_router",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_exact_router.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _b(eid, x, y, w, l, *, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), False, 1, th, None, None, f"b{eid}")


def test_reconstruct_fixed_overrides_footprints_from_best():
    # loaded layout has canonical positions; `best` moves them.
    region = Region(frozenset((x, y) for x in range(5) for y in range(5)))
    loaded = Layout(region, [_b(1, 0, 0, 2, 2, th=True), _b(2, 0, 0, 1, 1)], None, {})
    best = {"buildings": {"1": [0, 0, 2, 2], "2": [3, 4, 1, 1]}}
    fixed = mod.reconstruct_fixed(loaded, best)
    by_id = {b.entity_id: b for b in fixed.buildings}
    assert (by_id[2].footprint.x, by_id[2].footprint.y) == (3, 4)   # moved
    assert fixed.townhall is not None and fixed.townhall.entity_id == 1  # TH re-found
