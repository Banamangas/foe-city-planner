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


def _region_grid(w, h):
    from foeopt.model import Region
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_valid_actions_prior_is_subset_of_full():
    th = _b(1, 2, 2, needs=False, th=True)
    env = _env(_region_grid(10, 10), [th, _b(10, 3, 2), _b(11, 2, 2)])
    env.reset()
    full = set(env.valid_actions())
    prior = set(env.valid_actions(prior=True))
    assert prior <= full
    assert prior, "with the TH placed, the frontier is non-empty"


def test_valid_actions_prior_anchors_border_occupancy():
    th = _b(1, 2, 2, needs=False, th=True)          # TH occupies (0,0),(1,0),(0,1),(1,1)
    env = _env(_region_grid(10, 10), [th, _b(10, 2, 2)])
    env.reset()
    prior = env.valid_actions(prior=True)
    # every prior anchor's footprint must be orthogonally adjacent to the TH
    from foeopt.model import Footprint
    th_cells = th.footprint.cells()
    for (x, y) in prior:
        fp = Footprint(x, y, 2, 2)
        assert fp.border_cells() & th_cells, f"anchor {(x,y)} not adjacent to TH"


def test_valid_actions_prior_can_be_empty_when_full_is_not():
    # A 2-wide left arm holds the corner TH; a 7-wide right arm holds the only
    # fits for a 3x3; a 1-cell bridge connects them. The 3x3 can't fit in the
    # left arm or the bridge, so every legal anchor is in the right arm, none
    # adjacent to the TH -> prior empty, full non-empty.
    from foeopt.model import Region
    left = {(x, y) for x in (0, 1) for y in range(10)}
    bridge = {(2, 0)}
    right = {(x, y) for x in range(3, 10) for y in range(10)}
    region = Region(frozenset(left | bridge | right))
    th = _b(1, 2, 2, needs=False, th=True)
    env = _env(region, [th, _b(10, 3, 3)])
    env.reset()
    assert env.valid_actions(), "full set must be non-empty (3x3 fits in the right arm)"
    assert env.valid_actions(prior=True) == [], "no 3x3 placement borders the TH across the bridge"


def test_valid_actions_prior_empty_after_nothing_placed_is_frontier():
    # sanity: prior is non-empty right after reset because the TH is occupied
    th = _b(1, 3, 3, needs=False, th=True)
    env = _env(_region_grid(9, 9), [th, _b(10, 2, 2)])
    env.reset()
    assert env.valid_actions(prior=True)


def test_invalid_penalty_scales_with_unplaced():
    # 4 buildings to place after TH. Fail on the FIRST placement -> 4 unplaced.
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region_grid(3, 1), [th, _b(10, 1, 1), _b(11, 1, 1),
                                    _b(12, 1, 1), _b(13, 1, 1)])
    env.reset()
    res = env.step((0, 0))                       # overlaps TH -> invalid, 4 left
    assert res.info["error"] == "invalid_placement"
    assert res.reward == -100.0 * (4 / 4)


def test_invalid_penalty_scales_down_when_most_placed():
    # Place 3 of 4 successfully on a roomy grid, then force an invalid step.
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region_grid(8, 1), [th, _b(10, 1, 1), _b(11, 1, 1),
                                    _b(12, 1, 1), _b(13, 1, 1)])
    env.reset()
    env.step((2, 0)); env.step((3, 0)); env.step((4, 0))   # 3 placed, 1 left
    res = env.step((0, 0))                       # overlaps TH -> invalid, 1 unplaced
    assert res.reward == -100.0 * (1 / 4)


def test_unroutable_penalty_is_flat():
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region_grid(2, 1), [th, _b(10, 1, 1)])   # no room for a road
    env.reset()
    res = env.step((1, 0))
    assert res.reward == -100.0


def test_potential_shaping_rewards_road_needing_placement():
    th = _b(1, 2, 2, needs=False, th=True)
    cons = _b(10, 4, 4, needs=True)              # road-needing; road_estimate rises 2
    filler = _b(11, 2, 2, needs=False)           # not road-needing; estimate unchanged
    tail = _b(12, 2, 2, needs=True)              # last so filler's step is non-terminal
    env = PlacementEnv(Layout(_region_grid(20, 20), [th, cons, filler, tail], th),
                       placement_reward=0.0, potential_shaping=True)
    env.reset()
    # order is largest-area first: cons(16), then filler(4) and tail(4) by entity_id.
    # place the consumer first -> shaping bonus = road_estimate delta = min(4,4)//2 = 2
    r_cons = env.step(env.valid_actions()[0])
    assert not r_cons.done
    assert r_cons.reward == 2.0
    # place the filler next -> not road-needing, road_estimate unchanged -> reward 0.0
    r_filler = env.step(env.valid_actions()[0])
    assert not r_filler.done
    assert r_filler.reward == 0.0


def test_potential_shaping_off_by_default():
    th = _b(1, 2, 2, needs=False, th=True)
    cons = _b(10, 4, 4, needs=True)
    tail = _b(11, 2, 2, needs=True)              # so the first placement is non-terminal
    env = PlacementEnv(Layout(_region_grid(20, 20), [th, cons, tail], th),
                       placement_reward=0.0)
    env.reset()
    # shaping off, not terminal -> plain placement_reward (0.0)
    assert env.step(env.valid_actions()[0]).reward == 0.0


def test_valid_actions_safe_is_subset_of_full():
    th = _b(1, 2, 2, needs=False, th=True)
    env = _env(_region_grid(10, 10), [th, _b(10, 3, 2), _b(11, 2, 2)])
    env.reset()
    assert set(env.valid_actions(safe=True)) <= set(env.valid_actions())
    assert env.valid_actions(safe=True)


def test_safe_mask_forbids_walling_off_a_pocket():
    # 1-wide corridor region: TH at the left, a 1x1 anywhere strictly inside
    # the corridor would strand the right side -> only end placements are safe
    from foeopt.model import Region
    region = Region(frozenset((x, 0) for x in range(8)))
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(region, [th, _b(10, 1, 1), _b(11, 1, 1)])
    env.reset()
    safe = env.valid_actions(safe=True)
    assert (7, 0) in safe                # corridor end: nothing stranded
    assert (4, 0) not in safe            # mid-corridor: strands (5..7, 0)


def test_safe_rollouts_never_end_unroutable():
    import random as _random
    rng = _random.Random(0)
    for seed in range(10):
        th = _b(1, 2, 2, needs=False, th=True)
        bs = [_b(10 + i, rng.choice([2, 3]), rng.choice([2, 3]),
                 needs=rng.random() < 0.7) for i in range(8)]
        env = _env(_region_grid(10, 10), [th, *bs])
        env.reset()
        res = None
        while not env.done:
            acts = env.valid_actions(safe=True)
            if not acts:
                break                      # stuck is allowed; unroutable is not
            res = env.step(rng.choice(acts))
        if res is not None and res.done:
            assert res.info.get("error") != "unroutable"
