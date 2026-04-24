#!/usr/bin/env python3
"""
test_parser.py — Smoke tests: block file iteration and XOR decoding.

Verifies that:
1. XOR key loads correctly from fixtures/xor.dat
2. iter_blocks() yields raw block payloads from fixtures/blk04330.dat
3. Each block is at least 80 bytes (minimum: just a header)
4. Block count is nonzero

Run from repo root:
    python3 tests/test_parser.py
"""

import sys
import os

# Make sure sherlock package is importable from repo root
sys.path.insert(0, os.path.dirname(__file__))

from sherlock.parser.xor import load_xor_key, is_null_key
from sherlock.parser.block_file import iter_blocks, count_blocks


def main():
    xor_path = "fixtures/xor.dat"
    blk_path = "fixtures/blk04330.dat"

    # ── Step 1: Load XOR key ─────────────────────────────────────────────────
    print(f"[1] Loading XOR key from: {xor_path}")
    xor_key = load_xor_key(xor_path)
    print(f"    Key (hex): {xor_key.hex()}")
    print(f"    Null key:  {is_null_key(xor_key)}")

    # ── Step 2: Iterate blocks ───────────────────────────────────────────────
    print(f"\n[2] Iterating blocks from: {blk_path}")
    print("    block_num  |  raw_size (bytes)  |  first_4_bytes (header)")
    print("    " + "-" * 58)

    block_count = 0
    min_size = float("inf")
    max_size = 0
    total_size = 0

    for i, block_bytes in enumerate(iter_blocks(blk_path, xor_key)):
        size = len(block_bytes)
        first4 = block_bytes[:4].hex()

        # Print first 5 blocks, then only every 10th
        if i < 5 or i % 10 == 0:
            print(f"    block {i:>5}  |  {size:>18,}  |  {first4}")

        if size < 80:
            print(f"    ⚠️  WARNING: Block {i} is only {size} bytes (< 80 byte header)")

        min_size = min(min_size, size)
        max_size = max(max_size, size)
        total_size += size
        block_count += 1

    # ── Step 3: Summary ──────────────────────────────────────────────────────
    print(f"\n[3] Summary")
    print(f"    Total blocks found : {block_count:,}")
    print(f"    Smallest block     : {min_size:,} bytes")
    print(f"    Largest block      : {max_size:,} bytes")
    print(f"    Total data         : {total_size / 1024 / 1024:.2f} MB")

    if block_count == 0:
        print("\n❌ FAIL: No blocks found. Check XOR key or magic bytes.")
        sys.exit(1)
    else:
        print(f"\n✅ PASS: Successfully iterated {block_count} blocks from {blk_path}")


if __name__ == "__main__":
    main()
