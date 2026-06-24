import random

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.rlenv import PlacementEnv, Obs


def _b(eid, w=1, l=1, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(0, 0, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def _env(region, buildings):
    th = next(b for b in buildings if b.is_townhall)
    return PlacementEnv(Layout(region, buildings, th))


def test_reset_obs_and_townhall_preplaced():
    th = _b(1, 2, 2, needs=False, th=True)
    env = _env(_region(8, 8), [th, _b(10, 2, 2)])
    obs = env.reset()
    assert isinstance(obs, Obs)
    assert obs.occupied == th.footprint.cells()      # townhall down, nothing else
    assert obs.current_size == (2, 2) and obs.remaining == 1
    assert not env.done


def test_valid_actions_exclude_overlap_and_out_of_region():
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region(3, 1), [th, _b(10, 1, 1)])   # cells (0,0),(1,0),(2,0); TH at (0,0)
    assert env.valid_actions() == [(1, 0), (2, 0)]   # not (0,0) (TH), not off-grid


def test_terminal_reward_is_target_minus_roads():
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region(5, 1), [th, _b(10, 1, 1)])
    res = env.step((2, 0))                            # consumer at (2,0)
    assert res.done
    assert res.info["roads"] == 1                    # one road at (1,0) serves both
    assert res.info["target"] == env.target
    assert res.reward == env.target - 1              # sparse terminal reward


def test_invalid_action_is_penalized_and_terminal():
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region(3, 1), [th, _b(10, 1, 1)])
    res = env.step((0, 0))                            # overlaps the townhall
    assert res.done and res.reward == PlacementEnv.INVALID_PENALTY
    assert res.info["error"] == "invalid_placement"


def test_unroutable_dense_packing_penalized():
    # fill the whole 2x2 region with the TH + leave the consumer no road access
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region(2, 1), [th, _b(10, 1, 1)])    # cells (0,0),(1,0); TH at (0,0)
    res = env.step((1, 0))                            # consumer at (1,0): no free cell for a road
    assert res.done and res.reward == PlacementEnv.INVALID_PENALTY


def test_full_episode_random_completes_valid():
    th = _b(1, 2, 2, needs=False, th=True)
    cons = [_b(10 + i, 2, 2) for i in range(4)]
    env = PlacementEnv(Layout(_region(12, 12), [th, *cons], th))
    rng = random.Random(0)
    obs = env.reset()
    total = 0.0
    while not env.done:
        valid = env.valid_actions()
        assert valid                                 # roomy region -> always placeable
        res = env.step(rng.choice(valid))
        total += res.reward
    assert "roads" in res.info                        # a complete, routed layout
    assert res.reward == env.target - res.info["roads"]


def test_placement_reward_shaping():
    th = _b(1, 2, 2, needs=False, th=True)
    env = PlacementEnv(Layout(_region(12, 12), [th, _b(10, 2, 2), _b(11, 2, 2)], th),
                       placement_reward=0.5)
    res = env.step(env.valid_actions()[0])            # first placement, not terminal
    assert not res.done and res.reward == 0.5


def test_deterministic_same_actions_same_rewards():
    th = _b(1, 2, 2, needs=False, th=True)
    layout = Layout(_region(12, 12), [th, _b(10, 2, 2), _b(11, 3, 2)], th)
    def run():
        e = PlacementEnv(layout)
        e.reset()
        return [e.step(e.valid_actions()[0]).reward for _ in range(2)]
    assert run() == run()
