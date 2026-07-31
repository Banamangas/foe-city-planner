#!/bin/bash
# Track F step-2 calibration: does the opts_total population prefilter (and the
# widened pitch range) raise the SAT yield of the wide-shallow screen?
#
# Arm A is NOT re-run -- it is the recorded 98-road baseline
# (output/wide-screen.jsonl: 1400 probes, 20 SATs, 72.8 core-h, min achieved 98,
# same k-levels / budget / seed, default pitches, no prefilter).
#
#   B1 = prefilter only          (default pitch range 5-11)   -> isolates the filter
#   B2 = prefilter + new pitches (12-18, never probed)        -> isolates the range
#
# Both arms run CONCURRENTLY at 6 workers each = 12 of 16 cores, matching the
# validated headroom (lessons 2026-07-19/20: filling all 16 reproducibly
# backfires). Probes are single-threaded, so splitting workers across two arms
# costs nothing per probe -- it just halves wall-clock vs running them serially.
set -u
cd /home/born/Github/foe-city-planner
mkdir -p output/trackf

COMMON="--k-levels 105,106 --n 150 --budget 300 --workers 6 --seed 0 --prefilter-top 0.10"

echo "=== $(date '+%F %T') START B1 (prefilter only, pitches 5-11) ==="
uv run --with ortools python scripts/exp_wide_skeleton_screen.py darkzig.json \
    $COMMON --out output/trackf/b1.jsonl --sat-dir output/trackf/b1-sats \
    > output/trackf/b1.log 2>&1 &
B1=$!

echo "=== $(date '+%F %T') START B2 (prefilter + pitches 12-18) ==="
uv run --with ortools python scripts/exp_wide_skeleton_screen.py darkzig.json \
    $COMMON --pitches 12-18 --out output/trackf/b2.jsonl --sat-dir output/trackf/b2-sats \
    > output/trackf/b2.log 2>&1 &
B2=$!

wait $B1; echo "=== $(date '+%F %T') B1 exit=$? ==="
wait $B2; echo "=== $(date '+%F %T') B2 exit=$? ==="
echo "=== $(date '+%F %T') ALL DONE ==="
