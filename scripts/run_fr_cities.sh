#!/bin/bash
# Run roads-first on the three FR cities sequentially, 2h each, archiving between.
set -e
cd /home/born/Github/foe-city-planner
COMMON="--th-anchors full --patterns 200 --probe-limit 60.0 --time-box 7200.0 --workers 4 --probe-workers 4"
for city in CityMap-Born-FR16-2026-07-07 CityMap-Born-FR17-2026-07-07 CityMap-Born-FR24-2026-07-07; do
    short=$(echo $city | sed -E 's/CityMap-Born-(FR[0-9]+)-.*/\1/')
    out=output/roads-first/$short-2026-07-07
    mkdir -p $out
    echo "=== $(date '+%H:%M:%S') START $short (k_start auto) ==="
    uv run --with ortools python scripts/exp_roads_first.py ${city}.json $COMMON > $out/run.txt 2>&1 || echo "EXIT=$?"
    mv output/roads-first/probes.jsonl $out/probes.jsonl 2>/dev/null
    mv output/roads-first/best-k*.json $out/ 2>/dev/null
    mv output/roads-first/best-k*.html $out/ 2>/dev/null
    echo "=== $(date '+%H:%M:%S') DONE $short ==="
done
echo "=== $(date '+%H:%M:%S') ALL DONE ==="