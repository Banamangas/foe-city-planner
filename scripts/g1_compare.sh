#!/bin/bash
# G1 second-half: baseline vs CNN-guided k-walk on darkzig, 30min each, equal config.
cd /home/born/Github/foe-city-planner
echo "=== $(date '+%T') BASELINE (no scorer, 30min) ==="
uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 1800 \
    > output/kwalk/baseline.log 2>&1 || echo "baseline EXIT=$?"
echo "=== $(date '+%T') GUIDED (CNN scorer, 30min) ==="
uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 1800 \
    --scorer output/kwalk/cnn.pt > output/kwalk/guided.log 2>&1 || echo "guided EXIT=$?"
echo "=== $(date '+%T') DONE ==="
echo "--- BASELINE verdict ---"; grep -A8 '"verdict"' output/kwalk/baseline.log | head -9
echo "--- GUIDED verdict ---";   grep -A8 '"verdict"' output/kwalk/guided.log | head -9
