#!/bin/bash
# next-things-to-try.md idea #1: prune-mode guided walk sweep vs baseline, 30min/arm.
# Baseline (no scorer) already exists at output/kwalk/baseline.log (k=111, roads=102).
set -e
cd /home/born/Github/foe-city-planner
for t in 0.1 0.2 0.3 0.4; do
    echo "=== $(date '+%T') THRESHOLD $t (30min) ==="
    uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 1800 \
        --scorer output/kwalk/cnn.pt --score-threshold $t \
        > output/kwalk/prune-$t.log 2>&1 || echo "threshold=$t EXIT=$?"
done
echo "=== $(date '+%T') SWEEP DONE ==="
echo "--- BASELINE (reused) ---"; grep -A8 '"verdict"' output/kwalk/baseline.log | head -9
for t in 0.1 0.2 0.3 0.4; do
    echo "--- THRESHOLD $t ---"; grep -A8 '"verdict"' output/kwalk/prune-$t.log | head -9
done
