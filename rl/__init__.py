"""Optional RL training package for FoE layout (needs the `[rl]` extra: torch,
numpy). The pure-stdlib environment lives in foeopt/rlenv.py; this package adds
the policy network, PPO loop, and curriculum that drive it. Nothing here is
imported by the foeopt core — install `[rl]` and run `python -m rl.train` to use.

See rl/README.md for how to train, and docs/superpowers/specs for the design.
"""
