import torch

from rl.gate import run_gate


def test_gate_verdict_stuck_when_policy_cannot_place(tmp_path):
    # an untrained tiny policy on a tiny city -> likely stuck or high roads;
    # we only assert the verdict vocabulary and that roads/status are returned.
    from rl.policy import PlacementPolicy
    from foeopt.loader import load_layout
    layout = load_layout("city-user-data.json", "city-user-data-foe-helper.json")
    ckpt = tmp_path / "c.pt"
    torch.save({"state_dict": PlacementPolicy(hidden=64).state_dict(), "hidden": 64}, ckpt)
    r = run_gate(str(ckpt), "city-user-data.json", helper="city-user-data-foe-helper.json",
                 floor=158)
    assert r["status"] in ("ok", "stuck", "unroutable")
    assert r["verdict"] in ("beats_floor", "competitive", "stuck", "unroutable")
    assert r["floor"] == 158
    assert isinstance(r["target"], int)
    if r["status"] == "ok":
        assert isinstance(r["roads"], int)
        assert isinstance(r["quality"], dict)


def test_gate_beats_floor_when_roads_under_floor():
    # directly exercise the verdict logic with a stub result
    from rl.gate import _verdict
    assert _verdict(150, "ok", floor=158) == "beats_floor"   # <= floor
    assert _verdict(158, "ok", floor=158) == "beats_floor"   # at the floor
    assert _verdict(165, "ok", floor=158) == "competitive"   # above floor
    assert _verdict(None, "stuck", floor=158) == "stuck"
    assert _verdict(None, "unroutable", floor=158) == "unroutable"
