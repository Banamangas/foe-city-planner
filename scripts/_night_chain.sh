#!/usr/bin/env bash
# Overnight 2026-11-12: sequential A/B chain (fill, deep10r; 600 s then 120 s).
cd "$(dirname "$0")/.."
E=".venv/bin/python scripts/exp_objective_ab.py"
C="--cities FR17,FR16,darkzig --reps 2"
timeout 5400 $E --out scripts/_fill_ab.jsonl --box 600 $C --arms fill
timeout 5400 $E --out scripts/_deep10r_ab.jsonl --box 600 $C --arms deep10r
timeout 2400 $E --out scripts/_fill_ab.jsonl --box 120 $C --arms fill
timeout 2400 $E --out scripts/_deep10r_ab.jsonl --box 120 $C --arms deep10r
echo NIGHT_CHAIN_DONE
