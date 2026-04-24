"""
web/server.py — Sherlock Web API Server

Serves:
    GET  /                  → web/static/index.html (dashboard)
    GET  /api/health        → {"ok": true}
    GET  /api/blocks        → union of analyzed (out/*.json) and available fixture datasets
    GET  /api/block/<stem>  → contents of out/<stem>.json
    POST /api/analyze       → run analysis on a fixture dataset by name
    POST /api/upload        → accept a .dat file, run analysis, return report

Usage:
    python3 web/server.py [PORT]
    PORT=3000 python3 web/server.py

Python stdlib only — no external dependencies.
"""

import email.parser
import http.server
import io
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).parent.parent
OUT_DIR     = REPO_ROOT / "out"
FIXTURES_DIR = REPO_ROOT / "fixtures"
UPLOADS_DIR = FIXTURES_DIR / "uploads"
STATIC_DIR  = Path(__file__).parent / "static"

# ── Limits ───────────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 200 * 1024 * 1024   # 200 MB hard cap
MAX_JSON_BODY    = 64 * 1024           # 64 KB for JSON POST bodies

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_stem(raw: str) -> str:
    """
    Return a filesystem-safe stem string (alphanumeric, hyphen, underscore only).
    Returns empty string if nothing valid remains — caller must check.
    """
    return "".join(c for c in raw if c.isalnum() or c in "-_")


def _run_analysis(blk_path: Path, rev_path, xor_path, stem: str) -> dict:
    """
    Import and run the Sherlock analysis pipeline.

    Args:
        blk_path: Path to blk*.dat file.
        rev_path: Path to rev*.dat file, or None.
        xor_path: Path to xor.dat, or None.
        stem:     Output file stem (used to write out/<stem>.json).

    Returns:
        The parsed JSON report dict.  Always includes ``analysis_time_sec``
        (float, wall-clock seconds the pipeline took).

    Raises:
        Exception on analysis failure.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from sherlock.analysis.analyzer import analyze  # noqa: PLC0415

    t0 = time.time()
    result = analyze(
        blk_path=blk_path,
        rev_path=rev_path if (rev_path and rev_path.exists()) else None,
        xor_path=xor_path if (xor_path and xor_path.exists()) else None,
        out_dir=OUT_DIR,
        verbose=False,
    )
    elapsed = round(time.time() - t0, 2)

    json_path = result["json_path"]
    report = json.loads(json_path.read_bytes())
    report["analysis_time_sec"] = elapsed
    # Persist timing so cached loads also show real time
    json_path.write_text(json.dumps(report, indent=2))
    return report


def _parse_multipart(headers, body: bytes):
    """
    Parse a multipart/form-data body using stdlib only.

    Returns:
        (filename: str, file_bytes: bytes) or raises ValueError.
    """
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Content-Type must be multipart/form-data")

    # Build a minimal RFC 2822-style message so email.parser can handle it
    msg_text = f"Content-Type: {content_type}\r\n\r\n".encode() + body
    msg = email.parser.BytesParser().parsebytes(msg_text)

    for part in msg.get_payload():
        if not isinstance(part, email.message.Message):
            continue
        cd = part.get("Content-Disposition", "")
        if 'name="file"' not in cd and "name=file" not in cd:
            continue
        # Extract filename
        fname = None
        for token in cd.split(";"):
            token = token.strip()
            if token.lower().startswith("filename="):
                fname = token[9:].strip().strip('"').strip("'")
                break
        if not fname:
            raise ValueError("No filename in Content-Disposition")
        payload = part.get_payload(decode=True)
        if payload is None:
            raise ValueError("Empty file payload")
        return fname, payload

    raise ValueError("No 'file' field found in multipart body")


# ── Request handler ──────────────────────────────────────────────────────────

class SherlockHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        """Suppress noisy default access logging."""
        pass

    # ── Response helpers ─────────────────────────────────────────────────────

    # Errors that mean the client hung up mid-response — harmless, no traceback needed.
    _PIPE_ERRORS = (BrokenPipeError, ConnectionResetError)

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except self._PIPE_ERRORS:
            pass  # client disconnected — not an error

    def send_file(self, path: Path, mime: str):
        try:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_json({"ok": False, "error": "File not found"}, 404)
        except self._PIPE_ERRORS:
            pass  # client disconnected — not an error

    # ── GET ──────────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        # /api/health
        if path == "/api/health":
            self.send_json({"ok": True})
            return

        # /api/blocks — union of analyzed results AND available fixture files.
        # This ensures the dropdown is never empty on a fresh clone.
        if path == "/api/blocks":
            analyzed_stems = set(
                f.stem for f in OUT_DIR.glob("*.json")
            ) if OUT_DIR.exists() else set()

            fixture_stems = set()
            if FIXTURES_DIR.exists():
                for f in FIXTURES_DIR.glob("blk*.dat"):
                    fixture_stems.add(f.stem)
            if UPLOADS_DIR.exists():
                for f in UPLOADS_DIR.glob("*.dat"):
                    fixture_stems.add(f.stem)

            all_stems = sorted(analyzed_stems | fixture_stems)
            blocks = [
                {"stem": s, "analyzed": s in analyzed_stems}
                for s in all_stems
            ]
            self.send_json({"ok": True, "blocks": blocks})
            return

        # /api/block/<stem> — serve precomputed report
        if path.startswith("/api/block/"):
            stem = _safe_stem(path[len("/api/block/"):])
            if not stem:
                self.send_json({"ok": False, "error": "Invalid dataset name"}, 400)
                return
            json_file = OUT_DIR / f"{stem}.json"
            if not json_file.exists():
                self.send_json({
                    "ok": False,
                    "error": f"No analysis found for '{stem}'. "
                             f"Select a dataset and click 'Run Analysis'."
                }, 404)
                return
            try:
                data = json.loads(json_file.read_bytes())
                self.send_json(data)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return


        # Static files
        if path == "/" or path == "/index.html":
            self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        rel         = path.lstrip("/")
        static_file = STATIC_DIR / rel
        if static_file.exists() and static_file.is_file():
            ext  = static_file.suffix.lower()
            mime = MIME_TYPES.get(ext, "application/octet-stream")
            self.send_file(static_file, mime)
            return

        self.send_json({"ok": False, "error": f"Not found: {path}"}, 404)

    # ── POST ─────────────────────────────────────────────────────────────────

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/api/analyze":
            self._handle_analyze()
            return

        if path == "/api/upload":
            self._handle_upload()
            return

        self.send_json({"ok": False, "error": f"Not found: {path}"}, 404)

    # ── /api/analyze ─────────────────────────────────────────────────────────

    def _handle_analyze(self):
        """
        POST /api/analyze
        Body: {"dataset": "blk04330"}

        Locates fixtures/<dataset>.dat (and matching rev*.dat / xor.dat),
        runs the full Sherlock pipeline, writes out/<dataset>.json, and
        returns the JSON report.
        """
        # Read body (capped)
        length = min(int(self.headers.get("Content-Length", 0)), MAX_JSON_BODY)
        body   = self.rfile.read(length)

        try:
            payload = json.loads(body)
        except Exception:
            self.send_json({"ok": False, "error": "Invalid JSON body"}, 400)
            return

        raw_dataset = str(payload.get("dataset", "")).strip()
        stem = _safe_stem(raw_dataset)
        if not stem:
            self.send_json({"ok": False, "error": "Missing or invalid 'dataset' field"}, 400)
            return

        # Resolve blk path — check main fixtures dir, then uploads dir
        blk_path = FIXTURES_DIR / f"{stem}.dat"
        if not blk_path.exists():
            blk_path = UPLOADS_DIR / f"{stem}.dat"
        if not blk_path.exists():
            self.send_json({
                "ok": False,
                "error": f"Block file not found: fixtures/{stem}.dat — "
                         f"upload it first or use an existing fixture."
            }, 404)
            return

        # Derive rev stem: replace leading "blk" with "rev"
        if stem.startswith("blk"):
            rev_stem = "rev" + stem[3:]
        else:
            rev_stem = "rev_" + stem

        rev_path = FIXTURES_DIR / f"{rev_stem}.dat"
        xor_path = FIXTURES_DIR / "xor.dat"

        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            report = _run_analysis(blk_path, rev_path, xor_path, stem)
            self.send_json(report)
        except Exception as exc:
            self.send_json({
                "ok": False,
                "error": {"code": "ANALYSIS_ERROR", "message": str(exc)}
            }, 500)

    # ── /api/upload ──────────────────────────────────────────────────────────

    def _handle_upload(self):
        """
        POST /api/upload  (multipart/form-data, field name: "file")

        1. Validate file extension (.dat only)
        2. Enforce 200 MB size cap
        3. Save to fixtures/uploads/<safe_name>.dat
        4. Resolve rev*.dat: check fixtures/uploads/ then fixtures/ for a
           matching undo file (same numeric suffix pattern as _handle_analyze)
        5. Run analysis pipeline with xor.dat if present
        6. Return JSON report

        Edge cases handled:
        - Non-.dat files rejected (400)
        - Files exceeding MAX_UPLOAD_BYTES rejected (413)
        - Path traversal in filename neutralised by _safe_stem
        - Missing Content-Length → read up to cap
        - Analysis failure surfaces clean error message (500)
        """
        content_length = int(self.headers.get("Content-Length", 0))

        if content_length > MAX_UPLOAD_BYTES:
            self.send_json({
                "ok": False,
                "error": f"File too large. Maximum allowed: {MAX_UPLOAD_BYTES // (1024*1024)} MB"
            }, 413)
            return

        # Read body (bounded)
        body = self.rfile.read(content_length)

        # Parse multipart
        try:
            raw_filename, file_bytes = _parse_multipart(self.headers, body)
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        # Validate extension
        raw_filename = Path(raw_filename).name          # strip any directory component
        suffix = Path(raw_filename).suffix.lower()
        if suffix != ".dat":
            self.send_json({
                "ok": False,
                "error": f"Only .dat files are accepted (got '{suffix}')"
            }, 400)
            return

        # Build safe filename: keep stem, force .dat suffix
        raw_stem = Path(raw_filename).stem
        safe_name = _safe_stem(raw_stem) or "uploaded"
        dest_filename = f"{safe_name}.dat"

        # Double-check size after parsing
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            self.send_json({
                "ok": False,
                "error": f"File content exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit"
            }, 413)
            return

        if len(file_bytes) == 0:
            self.send_json({"ok": False, "error": "Uploaded file is empty"}, 400)
            return

        # Save file
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        dest_path = UPLOADS_DIR / dest_filename
        try:
            dest_path.write_bytes(file_bytes)
        except OSError as exc:
            self.send_json({"ok": False, "error": f"Could not save file: {exc}"}, 500)
            return

        # Resolve companion files.
        # Rev file: derive from filename pattern (blkXXXXX → revXXXXX).
        # Search uploads dir first, then main fixtures dir.
        if safe_name.startswith("blk"):
            rev_stem = "rev" + safe_name[3:]
        else:
            rev_stem = "rev_" + safe_name

        rev_path = None
        for search_dir in (UPLOADS_DIR, FIXTURES_DIR):
            candidate = search_dir / f"{rev_stem}.dat"
            if candidate.exists():
                rev_path = candidate
                break

        xor_path = FIXTURES_DIR / "xor.dat"

        # Return the safe_name so the frontend can add it to the dropdown
        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            report = _run_analysis(
                blk_path=dest_path,
                rev_path=rev_path,
                xor_path=xor_path,
                stem=safe_name,
            )
            # Include the stem so the frontend knows which name to add
            report["dataset"] = safe_name
            self.send_json(report)
        except Exception as exc:
            self.send_json({
                "ok": False,
                "error": {"code": "ANALYSIS_ERROR", "message": str(exc)}
            }, 500)


# ── Entry point ──────────────────────────────────────────────────────────────

class _QuietHTTPServer(http.server.HTTPServer):
    """Suppress BrokenPipeError / ConnectionResetError tracebacks.

    These happen when a browser cancels a request or refreshes before the
    server finishes writing.  They are not bugs — just noise without this.
    """

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return  # client disconnected — ignore silently
        # All other errors log the usual traceback
        super().handle_error(request, client_address)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 3000))
    # Bind to all interfaces when PORT is injected by a hosting platform (Railway, Render…).
    # Local runs via web.sh do not export PORT so os.environ won't have it → stays on localhost.
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    server = _QuietHTTPServer((host, port), SherlockHandler)
    print(f"http://{host}:{port}")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
