#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

echo "Activate with: source .venv/bin/activate"

./.venv/bin/python -m pip install -U pip
./.venv/bin/pip install -e .

echo "Bootstrap complete."
