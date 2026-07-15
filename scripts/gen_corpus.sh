#!/bin/bash
# Track C-bis Stage 0 -> corpus generation: darkzig (2h) then FR16 (2h).
cd /home/born/Github/foe-city-planner
COMMON="--patterns 200 --probe-limit 30 --workers 6 --probe-workers 2 --th-anchors full"
echo "=== $(date '+%F %T') START darkzig (2h) ==="
uv run python scripts/exp_roads_first.py darkzig.json --corpus output/corpus/darkzig \
    --time-box 7200 $COMMON > output/corpus/darkzig-gen.log 2>&1 || echo "darkzig EXIT=$?"
echo "=== $(date '+%F %T') START FR16 (2h) ==="
uv run python scripts/exp_roads_first.py CityMap-Born-FR16-2026-07-07.json --corpus output/corpus/FR16 \
    --time-box 7200 $COMMON > output/corpus/FR16-gen.log 2>&1 || echo "FR16 EXIT=$?"
echo "=== $(date '+%F %T') DONE. instances: darkzig=$(wc -l < output/corpus/darkzig/instances.jsonl) FR16=$(wc -l < output/corpus/FR16/instances.jsonl) ==="
