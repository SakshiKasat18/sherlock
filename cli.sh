#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# cli.sh — Sherlock Bitcoin Chain Analysis CLI
#
# Usage:
#   ./cli.sh --block <blk.dat> <rev.dat> <xor.dat>
#
# Outputs:
#   out/<blk_stem>.json   — machine-readable analysis report (grader schema)
#   out/<blk_stem>.md     — human-readable Markdown report
#
# Exit codes: 0 = success, 1 = error
# Errors are printed as structured JSON to stdout.
###############################################################################

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

error_json() {
  local code="$1"
  local message="$2"
  printf '{"ok":false,"error":{"code":"%s","message":"%s"}}\n' "$code" "$message"
}

# --- Validate flag ---
if [[ "${1:-}" != "--block" ]]; then
  error_json "INVALID_ARGS" "Usage: ./cli.sh --block <blk.dat> <rev.dat> <xor.dat>"
  exit 1
fi
shift

# --- Validate argument count ---
if [[ $# -lt 3 ]]; then
  error_json "INVALID_ARGS" "Block mode requires exactly 3 file arguments"
  exit 1
fi

BLK_FILE="$1"
REV_FILE="$2"
XOR_FILE="$3"

# --- Validate files exist ---
for f in "$BLK_FILE" "$REV_FILE" "$XOR_FILE"; do
  if [[ ! -f "$f" ]]; then
    error_json "FILE_NOT_FOUND" "File not found: $f"
    exit 1
  fi
done

# --- Create output directory ---
mkdir -p out

# --- Run analysis engine ---
cd "$REPO_DIR"
"$PYTHON" - "$BLK_FILE" "$REV_FILE" "$XOR_FILE" << 'PYEOF'
import sys
import json
from pathlib import Path

sys.path.insert(0, ".")

blk_path = Path(sys.argv[1])
rev_path = Path(sys.argv[2])
xor_path = Path(sys.argv[3])

try:
    from sherlock.analysis.analyzer import analyze

    result = analyze(
        blk_path  = blk_path,
        rev_path  = rev_path,
        xor_path  = xor_path,
        out_dir   = Path("out"),
        verbose   = True,
    )

    print(json.dumps({
        "ok":         True,
        "json_path":  str(result["json_path"]),
        "md_path":    str(result["md_path"]),
        "block_count": result["block_count"],
    }))
    sys.exit(0)

except Exception as exc:
    import traceback
    print(json.dumps({
        "ok": False,
        "error": {
            "code":    "ANALYSIS_ERROR",
            "message": str(exc),
        }
    }))
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
PYEOF

STATUS=$?
exit $STATUS
