#!/usr/bin/env python3
"""
test_heuristics.py — Smoke tests: heuristic engine and transaction classification.

Run from repo root:
    python3 tests/test_heuristics.py
"""

import sys
import os
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from sherlock.parser.xor import load_xor_key
from sherlock.parser.block_file import iter_blocks
from sherlock.parser.block import parse_block
from sherlock.parser.undo import load_undo_file, resolve_prevouts
from sherlock.heuristics.engine import HEURISTICS, classify_transaction
from sherlock.analysis.classifier import classify_block


def main():
    xor_path = Path("fixtures/xor.dat")
    blk_path = Path("fixtures/blk04330.dat")
    rev_path = Path("fixtures/rev04330.dat")

    xor_key = load_xor_key(xor_path)
    print(f"XOR key  : {xor_key.hex()}")
    print(f"Blocks   : {blk_path}")
    print(f"Undo     : {rev_path}\n")

    print("[1] Loading undo records...")
    block_undos = load_undo_file(rev_path, xor_key)
    print(f"    {len(block_undos)} BlockUndo records\n")

    heuristic_ids = [h.ID for h in HEURISTICS]
    detection_counts = Counter()
    confidence_dist = {hid: Counter() for hid in heuristic_ids}
    classification_counts = Counter()
    total_tx = 0
    errors = 0

    print("[2] Running heuristic engine on all blocks...")
    hdr_cols = "  Block    Height     Tx    CIOH   ChgDt   CoinJ  Consol   Reuse   Round   Batch"
    print(hdr_cols)
    print("─" * len(hdr_cols))

    for block_idx, block_bytes in enumerate(iter_blocks(blk_path, xor_key)):
        try:
            block = parse_block(block_bytes)
        except Exception as exc:
            print(f"  ✗ Block {block_idx}: parse error — {exc}")
            errors += 1
            continue

        if block_idx < len(block_undos):
            try:
                resolve_prevouts(block, block_undos[block_idx])
            except Exception:
                pass

        try:
            classify_block(block)
        except Exception as exc:
            print(f"  ✗ Block {block_idx}: heuristic error — {exc}")
            errors += 1
            continue

        block_detect = Counter()
        for tx in block.transactions:
            total_tx += 1
            classification_counts[tx.classification] += 1
            for hid in heuristic_ids:
                result = tx.heuristics.get(hid, {})
                if result.get("detected"):
                    detection_counts[hid] += 1
                    block_detect[hid] += 1
                    confidence_dist[hid][result.get("confidence", "n/a")] += 1

        if block_idx < 5 or block_idx % 10 == 0:
            cols = [f"  {block_idx:>5}", f"{block.block_height:>8,}", f"{block.tx_count:>6,}"]
            for hid in heuristic_ids:
                cols.append(f"{block_detect[hid]:>7,}")
            print("  ".join(cols))

    print("\n" + "=" * 85)
    print("HEURISTIC DETECTION SUMMARY")
    print(f"  Total transactions  : {total_tx:,}")
    print(f"  Engine errors       : {errors}\n")
    print(f"  {'Heuristic':<26}  {'Detected':>10}  {'Pct':>6}  Confidence")
    print("  " + "─" * 70)

    for hid in heuristic_ids:
        hname = next(h.NAME for h in HEURISTICS if h.ID == hid)
        count = detection_counts[hid]
        pct = 100 * count / max(total_tx, 1)
        conf = "  ".join(f"{k}={v:,}" for k, v in confidence_dist[hid].most_common()) or "—"
        print(f"  {hname:<26}  {count:>10,}  {pct:>5.1f}%  {conf}")

    print("\n  CLASSIFICATION")
    print(f"  {'Label':<20}  {'Count':>10}  {'Pct':>6}")
    print("  " + "─" * 40)
    for label, count in classification_counts.most_common():
        print(f"  {label:<20}  {count:>10,}  {100*count/max(total_tx,1):>5.1f}%")

    print()
    passed = True
    def check(cond, msg):
        nonlocal passed
        mark = "✅" if cond else "❌"
        print(f"  {mark}  {msg}")
        if not cond: passed = False

    check(errors == 0, "No engine errors")
    check(detection_counts["cioh"] > 40_000,
          f"CIOH > 40k tx (got {detection_counts['cioh']:,})")
    check(detection_counts["change_detection"] > 40_000,
          f"Change detection > 40k tx (got {detection_counts['change_detection']:,})")
    check(detection_counts["round_number_payment"] > 0,
          f"Round number detected > 0 (got {detection_counts['round_number_payment']:,})")
    check(classification_counts.get("simple_payment", 0) > 0,
          f"simple_payment populated (got {classification_counts.get('simple_payment', 0):,})")
    check(sum(classification_counts.values()) == total_tx,
          "All transactions classified")

    print()
    if passed:
        print("✅  PASS: All heuristic engine checks passed")
    else:
        print("❌  FAIL: Some checks failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
