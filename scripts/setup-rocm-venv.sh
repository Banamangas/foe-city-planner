#!/usr/bin/env bash
# One-time setup of an AMD/ROCm GPU training venv for the RL stack.
# The portable CPU `rl` extra (uv sync --extra rl) stays untouched.
# Verified on RX 9070 XT (gfx1201) with ROCm 7.2 + torch 2.10.0+rocm7.0.
set -euo pipefail

VENV="${FOE_RL_VENV:-$HOME/.venv/foe-rl-rocm}"
ROCM_INDEX="https://download.pytorch.org/whl/rocm7.0"

if [ ! -d /opt/rocm ]; then
  echo "ERROR: ROCm not found at /opt/rocm. Install ROCm first." >&2
  exit 1
fi

echo "Creating venv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip

# torch + numpy from the ROCm index. TMPDIR on a big disk avoids tmpfs fill.
echo "Installing torch (ROCm wheel, ~3GB download)..."
TMPDIR="${TMPDIR:-$HOME/.cache/pip-tmp}" \
"$VENV/bin/pip" install --index-url "$ROCM_INDEX" torch numpy

echo "Verifying GPU..."
"$VENV/bin/python" - <<'PY'
import torch
assert torch.cuda.is_available(), "torch.cuda.is_available() is False — ROCm not visible"
print(f"torch {torch.__version__} | GPU: {torch.cuda.get_device_name(0)} | OK")
PY

cat <<EOF

Done. Train with (from the repo root):
  $VENV/bin/python -m rl.train --device cuda --auto --updates 3000 --episodes 64 --eval-city darkzig.json --ckpt rl_ckpt.pt

Eval:
  $VENV/bin/python -m rl.eval --ckpt rl_ckpt.pt --city darkzig.json
EOF
