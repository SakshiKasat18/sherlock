"""
analyzer.py — Main pipeline runner for Sherlock.

Orchestrates the full analysis pipeline:
    1. Iterate blocks from blk*.dat (with XOR decoding)
    2. Resolve prevouts from rev*.dat (fee computation)
    3. Run heuristic engine on every transaction
    4. Classify transactions
    5. Emit JSON + Markdown reports to out/

Public API:

    from sherlock.analysis.analyzer import analyze

    analyze(
        blk_path  = Path("fixtures/blk04330.dat"),
        rev_path  = Path("fixtures/rev04330.dat"),
        xor_path  = Path("fixtures/xor.dat"),
        out_dir   = Path("out"),
    )

Returns:
    dict with paths to generated files and summary statistics.
"""

from pathlib import Path
from typing import Optional
import sys

from ..parser.xor import load_xor_key
from ..parser.block_file import iter_blocks
from ..parser.block import parse_block
from ..parser.undo import load_undo_file, resolve_prevouts
from ..heuristics.engine import HEURISTICS, run_heuristics, classify_transaction
from .classifier import classify_block
from .report_json import build_json_report
from .report_md import build_md_report


def _iter_analyzed_blocks(
    blk_path: Path,
    rev_path: Optional[Path],
    xor_key: bytes,
):
    """
    Generator that yields fully analyzed ParsedBlock objects.

    Each block has:
        - All transactions parsed (SegWit-aware)
        - Prevouts resolved (if rev_path provided)
        - Fees and fee_rates computed
        - Heuristics applied (tx.heuristics populated)
        - Classifications set (tx.classification populated)

    Args:
        blk_path: Path to blk*.dat file.
        rev_path: Path to rev*.dat file (or None to skip prevout resolution).
        xor_key:  8-byte XOR decoding key.

    Yields:
        ParsedBlock — fully enriched.
    """
    # Load undo data upfront (rev*.dat is small enough to hold in memory)
    block_undos = []
    if rev_path and rev_path.exists():
        try:
            block_undos = load_undo_file(rev_path, xor_key)
        except Exception as exc:
            print(f"[analyzer] Warning: could not load undo file: {exc}",
                  file=sys.stderr)

    for block_idx, block_bytes in enumerate(iter_blocks(blk_path, xor_key)):
        block = parse_block(block_bytes)

        # Prevout resolution + fee computation
        if block_idx < len(block_undos):
            try:
                resolve_prevouts(block, block_undos[block_idx])
            except Exception as exc:
                print(
                    f"[analyzer] Warning: prevout resolution failed "
                    f"for block {block_idx}: {exc}",
                    file=sys.stderr,
                )

        # Heuristics + classification (in-place tx update)
        classify_block(block)

        yield block


def analyze(
    blk_path: Path,
    rev_path: Optional[Path] = None,
    xor_path: Optional[Path] = None,
    out_dir: Path = Path("out"),
    *,
    verbose: bool = True,
) -> dict:
    """
    Run the full Sherlock analysis pipeline on one blk*.dat file.

    Args:
        blk_path: Path to the blk*.dat file to analyze.
        rev_path: Path to the corresponding rev*.dat file (optional but recommended).
        xor_path: Path to xor.dat key file (optional; defaults to null key).
        out_dir:  Output directory for JSON and Markdown reports.
        verbose:  Print progress to stdout.

    Returns:
        dict containing:
            json_path (Path)     — path to generated JSON report
            md_path   (Path)     — path to generated Markdown report
            block_count (int)    — number of blocks analyzed
    """
    blk_path = Path(blk_path)
    out_dir  = Path(out_dir)

    # Load XOR key
    if xor_path and Path(xor_path).exists():
        xor_key = load_xor_key(Path(xor_path))
    else:
        xor_key = bytes(8)  # null key = no decoding

    blk_filename = blk_path.name

    if verbose:
        print(f"[Sherlock] Analyzing {blk_filename}")
        print(f"           rev: {rev_path}")
        print(f"           xor: {xor_key.hex()}")
        print(f"           out: {out_dir}")
        print()

    # We need two passes (JSON and MD both need the full block list),
    # but we want to avoid parsing twice. So we materialize the block list.
    # Memory usage: each ParsedBlock is relatively small (heuristic dicts, not raw bytes).
    if verbose:
        print(f"[Sherlock] Parsing + analyzing blocks...")

    all_blocks = list(_iter_analyzed_blocks(blk_path, rev_path, xor_key))
    block_count = len(all_blocks)

    if verbose:
        total_tx = sum(b.tx_count for b in all_blocks)
        print(f"           {block_count} blocks, {total_tx:,} transactions")
        print()

    # JSON report
    if verbose:
        print(f"[Sherlock] Writing JSON report...")
    json_path = build_json_report(
        iter(all_blocks),
        blk_filename=blk_filename,
        out_dir=out_dir,
    )
    if verbose:
        import os
        size_kb = os.path.getsize(json_path) / 1024
        print(f"           → {json_path}  ({size_kb:.1f} KB)")

    # Markdown report
    if verbose:
        print(f"[Sherlock] Writing Markdown report...")
    md_path = build_md_report(
        iter(all_blocks),
        blk_filename=blk_filename,
        out_dir=out_dir,
    )
    if verbose:
        import os
        size_kb = os.path.getsize(md_path) / 1024
        print(f"           → {md_path}  ({size_kb:.1f} KB)")
        print()
        print(f"[Sherlock] Done ✅")

    return {
        "json_path":   json_path,
        "md_path":     md_path,
        "block_count": block_count,
    }
