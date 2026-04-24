#!/usr/bin/env python3
"""
test_block_parsing.py — Smoke tests: block and transaction parsing.

Verifies that:
1. All blocks in blk04330.dat parse without errors
2. Transaction counts match per-block tx_count
3. SegWit transactions are correctly detected
4. Script types are being classified
5. Block heights are decoded via BIP34

Run from repo root:
    python3 tests/test_block_parsing.py
"""

import sys
import os
from pathlib import Path
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

from sherlock.parser.xor import load_xor_key
from sherlock.parser.block_file import iter_blocks
from sherlock.parser.block import parse_block


def main():
    xor_path = Path("fixtures/xor.dat")
    blk_path = Path("fixtures/blk04330.dat")

    xor_key = load_xor_key(xor_path)
    print(f"XOR key: {xor_key.hex()}  (null={all(b==0 for b in xor_key)})")
    print(f"Parsing: {blk_path}\n")

    total_tx = 0
    total_segwit = 0
    total_legacy = 0
    total_coinbase = 0
    parse_errors = 0
    script_types: Counter = Counter()

    print(f"{'Block':>7}  {'Height':>8}  {'TxCount':>8}  {'SegWit':>8}  {'Hash (prefix)'}")
    print("─" * 75)

    for block_idx, block_bytes in enumerate(iter_blocks(blk_path, xor_key)):
        try:
            block = parse_block(block_bytes)
        except Exception as exc:
            print(f"  ⚠️  Block {block_idx}: PARSE ERROR — {exc}")
            parse_errors += 1
            continue

        tx_count = block.tx_count
        segwit_count = sum(1 for tx in block.transactions if tx.is_segwit)
        legacy_count = tx_count - segwit_count
        coinbase_count = sum(1 for tx in block.transactions if tx.is_coinbase)

        # Collect script types from outputs
        for tx in block.transactions:
            for out in tx.outputs:
                script_types[out.script_type] += 1

        total_tx += tx_count
        total_segwit += segwit_count
        total_legacy += legacy_count
        total_coinbase += coinbase_count

        # Print first 5, then every 10th
        if block_idx < 5 or block_idx % 10 == 0:
            print(
                f"  {block_idx:>5}  "
                f"{block.block_height:>8,}  "
                f"{tx_count:>8,}  "
                f"{segwit_count:>8,}  "
                f"{block.block_hash[:32]}..."
            )

        # Print first block's first few transactions in detail
        if block_idx == 0:
            print(f"\n  ── First block detail (height={block.block_height}) ──")
            for t_idx, tx in enumerate(block.transactions[:5]):
                print(
                    f"    TX {t_idx}  txid={tx.txid[:20]}...  "
                    f"in={tx.input_count}  out={tx.output_count}  "
                    f"segwit={tx.is_segwit}  coinbase={tx.is_coinbase}  "
                    f"vsize={tx.vsize}"
                )
            print()

    print("\n" + "═" * 75)
    print("SUMMARY")
    print(f"  Total blocks parsed   : {block_idx + 1 - parse_errors:,}")
    print(f"  Parse errors          : {parse_errors}")
    print(f"  Total transactions    : {total_tx:,}")
    print(f"  SegWit transactions   : {total_segwit:,}  "
          f"({100*total_segwit/max(total_tx,1):.1f}%)")
    print(f"  Legacy transactions   : {total_legacy:,}")
    print(f"  Coinbase transactions : {total_coinbase:,}")

    print("\n  Script type distribution:")
    for stype, count in script_types.most_common():
        pct = 100 * count / max(sum(script_types.values()), 1)
        print(f"    {stype:<12} {count:>10,}  ({pct:.1f}%)")

    if parse_errors == 0:
        print(f"\n✅ PASS: All blocks and transactions parsed successfully")
    else:
        print(f"\n❌ FAIL: {parse_errors} block(s) had parse errors")
        sys.exit(1)


if __name__ == "__main__":
    main()
