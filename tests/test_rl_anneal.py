import random
import torch

from rl.ppo import prior_strength_for_success, select_action_mask


def test_prior_strength_strict_when_success_low():
    assert prior_strength_for_success(0.0) == 1.0
    assert prior_strength_for_success(0.5) == 1.0          # at the threshold, still strict


def test_prior_strength_relaxes_to_floor_as_success_rises():
    assert prior_strength_for_success(1.0) == 0.2          # floor
    mid = prior_strength_for_success(0.75)                 # halfway between 0.5 and 1.0
    assert 0.2 < mid < 1.0
    # monotonic: higher success -> lower (more relaxed) strength
    assert prior_strength_for_success(0.6) > prior_strength_for_success(0.9)


def test_select_mask_uses_full_when_prior_empty():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([False, False, False])
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=1.0, rng=rng)
    assert torch.equal(out, full)          # fallback: prior empty -> full


def test_select_mask_strict_uses_prior_when_nonempty():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([True, False, False])
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=1.0, rng=rng)
    assert torch.equal(out, prior)


def test_select_mask_zero_strength_uses_full():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([True, False, False])
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=0.0, rng=rng)
    assert torch.equal(out, full)


def test_select_mask_intermediate_flips_by_rng():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([True, False, False])
    # rng draws < 0.5 -> prior; >= 0.5 -> full. With seed 0, first draw is ~0.844 -> full.
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=0.5, rng=rng)
    assert torch.equal(out, full)