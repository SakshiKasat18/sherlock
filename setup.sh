#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# setup.sh — Install Sherlock dependencies
#
# Installs the package in editable mode with development dependencies,
# and decompresses block fixture files if not already present.
#
# Run once after cloning:
#   ./setup.sh
###############################################################################

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[setup] Installing Sherlock..."
pip install -e "${REPO_DIR}[dev]" --quiet

echo "[setup] Checking fixtures..."
for gz in "${REPO_DIR}/fixtures/"*.dat.gz; do
  [[ -f "$gz" ]] || continue
  dat="${gz%.gz}"
  if [[ ! -f "$dat" ]]; then
    echo "  Decompressing $(basename "$gz")..."
    gunzip -k "$gz"
  fi
done

echo "[setup] Done. Run 'make test' to verify the installation."
