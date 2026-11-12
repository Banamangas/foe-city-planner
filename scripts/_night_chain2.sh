#!/usr/bin/env bash
# Overnight 2026-11-12 (2): wide polish store (fillw), and pl10 + wide fill.
cd "$(dirname "$0")/.."
E=".venv/bin/python scripts/exp_objective_ab.py"
C="--cities FR17,FR16,darkzig --reps 2"
timeout 5400 $E --out scripts/_fillw_ab.jsonl --box 600 $C --arms fillw
timeout 5400 $E --out scripts/_fillw_ab.jsonl --box 600 $C --arms pl10fw
timeout 2400 $E --out scripts/_fillw_ab.jsonl --box 120 $C --arms fillw
timeout 2400 $E --out scripts/_fillw_ab.jsonl --box 120 $C --arms pl10fw
echo NIGHT_CHAIN2_DONE
