import random

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.rlenv import PlacementEnv


def _layout(n=8, side=14):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    rng = random.Random(0)
    bs = [Building(10 + i, f"c{10+i}", "g",
                   Footprint(0, 0, rng.choice([2, 3, 4]), rng.choice([2, 3, 4])),
                   rng.random() < 0.7, 1, False, None, None, f"b{10+i}")
          for i in range(n)]
    region = Region(frozenset((x, y) for x in range(side) for y in range(side)))
    return Layout(region, [th, *bs], th, {})


def test_cached_valid_actions_matches_uncached_across_an_episode():
    layout = _layout()
    slow = PlacementEnv(layout)
    fast = PlacementEnv(layout, cache_valid_actions=True)
    rng = random.Random(123)
    slow.reset(); fast.reset()
    while not slow.done:
        assert slow.valid_actions() == fast.valid_actions()
        assert slow.valid_actions(prior=True) == fast.valid_actions(prior=True)
        a = rng.choice(slow.valid_actions())
        slow.step(a); fast.step(a)
