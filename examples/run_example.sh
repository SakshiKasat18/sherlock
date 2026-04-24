#!/usr/bin/env bash
# examples/run_example.sh — Run Sherlock on the included fixture datasets
#
# Usage:
#   ./examples/run_example.sh              # analyzes blk04330.dat (default)
#   ./examples/run_example.sh blk05051     # analyzes blk05051.dat
#
# Output is written to out/<stem>.json and out/<stem>.md

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STEM="${1:-blk04330}"

BLK="$REPO_DIR/fixtures/${STEM}.dat"
REV="$REPO_DIR/fixtures/$(echo "$STEM" | sed 's/^blk/rev/').dat"
XOR="$REPO_DIR/fixtures/xor.dat"

if [[ ! -f "$BLK" ]]; then
  echo "Block file not found: $BLK"
  echo "Run: make install  (decompresses fixtures)"
  exit 1
fi

echo "Running Sherlock on: $STEM"
echo ""

cd "$REPO_DIR"
./cli.sh --block "$BLK" "$REV" "$XOR"
