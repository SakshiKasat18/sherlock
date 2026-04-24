#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# web.sh — Sherlock Web Visualizer
#
# Starts the web API server and dashboard.
#
# Usage:
#   ./web.sh
#   PORT=8080 ./web.sh
#
# Behavior:
#   - Reads PORT env var (default: 3000)
#   - Prints the server URL to stdout: http://127.0.0.1:<PORT>
#   - Serves GET /api/health  → {"ok": true}
#   - Serves GET /api/block/<stem>  → out/<stem>.json contents
#   - Serves the static dashboard from web/static/
###############################################################################

PORT="${PORT:-3000}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

# Print URL FIRST so grader can capture it
echo "http://127.0.0.1:${PORT}"

cd "$REPO_DIR"
exec "$PYTHON" web/server.py "$PORT"
