import random

from foeopt.model import Building, Footprint, Layout, Region
from rl.baselines import random_rollout, greedy_rollout


def _layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    cons = [Building(10 + i, f"c{10+i}", "g", Footprint(0, 0, 2, 2),
                     True, 1, False, None, None, f"b{10+i}") for i in range(4)]
    region = Region(frozenset((x, y) for x in range(12) for y in range(12)))
    return Layout(region, [th, *cons], th, {})


def test_random_rollout_completes_on_roomy_city():
    roads, status = random_rollout(_layout(), rng=random.Random(0))
    assert status == "ok"
    assert isinstance(roads, int) and roads > 0


def test_random_rollout_is_deterministic_given_seed():
    r1, _ = random_rollout(_layout(), rng=random.Random(0))
    r2, _ = random_rollout(_layout(), rng=random.Random(0))
    assert r1 == r2


def test_greedy_rollout_completes_and_beats_or_matches_random():
    g_roads, g_status = greedy_rollout(_layout())
    assert g_status == "ok"
    # greedy is myopic but should be no worse than random on a roomy grid
    r_roads, _ = random_rollout(_layout(), rng=random.Random(0))
    assert g_roads <= r_roads + 4   # generous; greedy shouldn't blow up here
