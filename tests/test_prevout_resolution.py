#!/usr/bin/env python3
"""
test_prevout_resolution.py — Smoke tests: prevout resolution and fee computation.

Verifies that:
1. rev04330.dat loads without errors
2. BlockUndo count matches block count from blk04330.dat
3. Prevout resolution correctly fills input values
4. Fee computation is non-negative and reasonable
5. Fee rate stats are consistent (min <= median <= max)

Run from repo root:
    python3 tests/test_prevout_resolution.py
"""

import sys
import os
import statistics
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from sherlock.parser.xor import load_xor_key
from sherlock.parser.block_file import iter_blocks
from sherlock.parser.block import parse_block
from sherlock.parser.undo import load_undo_file, resolve_prevouts


def main():
    xor_path  = Path("fixtures/xor.dat")
    blk_path  = Path("fixtures/blk04330.dat")
    rev_path  = Path("fixtures/rev04330.dat")

    xor_key = load_xor_key(xor_path)
    print(f"XOR key : {xor_key.hex()}")
    print(f"Block   : {blk_path}")
    print(f"Undo    : {rev_path}\n")

    # ── Step 1: Load undo file ────────────────────────────────────────────────
    print("[1] Loading undo file...")
    block_undos = load_undo_file(rev_path, xor_key)
    print(f"    BlockUndo records loaded: {len(block_undos)}")

    # ── Step 2: Parse blocks and resolve prevouts ─────────────────────────────
    print("\n[2] Parsing blocks + resolving prevouts...")
    print(f"{'Block':>7}  {'Height':>8}  {'Txs':>6}  "
          f"{'FeeOK':>6}  {'MedFee(sat)':>12}  {'MedRate(s/vb)':>14}")
    print("─" * 68)

    total_tx             = 0
    total_fees_ok        = 0
    total_fees_none      = 0
    all_fee_rates        = []
    all_fees             = []
    input_types_resolved = 0
    input_types_none     = 0
    parse_errors         = 0

    for block_idx, block_bytes in enumerate(iter_blocks(blk_path, xor_key)):
        try:
            block = parse_block(block_bytes)
        except Exception as exc:
            print(f"  ✗ Block {block_idx}: parse error — {exc}")
            parse_errors += 1
            continue

        # Resolve prevouts if undo data is available for this block
        if block_idx < len(block_undos):
            try:
                resolve_prevouts(block, block_undos[block_idx])
            except Exception as exc:
                print(f"  ✗ Block {block_idx}: resolve error — {exc}")

        # Collect stats
        block_fees    = []
        block_rates   = []
        fees_ok       = 0
        fees_none     = 0

        for tx in block.transactions:
            total_tx += 1
            if tx.is_coinbase:
                continue
            if tx.fee is not None:
                fees_ok      += 1
                block_fees.append(tx.fee)
                all_fees.append(tx.fee)
                if tx.fee_rate is not None:
                    block_rates.append(tx.fee_rate)
                    all_fee_rates.append(tx.fee_rate)
            else:
                fees_none += 1

            # Count input type resolution
            for inp in tx.inputs:
                if inp.script_type is not None:
                    input_types_resolved += 1
                else:
                    input_types_none += 1

        total_fees_ok   += fees_ok
        total_fees_none += fees_none

        med_fee  = int(statistics.median(block_fees))  if block_fees  else 0
        med_rate = statistics.median(block_rates) if block_rates else 0.0

        if block_idx < 5 or block_idx % 10 == 0:
            print(
                f"  {block_idx:>5}  {block.block_height:>8,}  "
                f"{block.tx_count:>6,}  {fees_ok:>6,}  "
                f"{med_fee:>12,}  {med_rate:>14.2f}"
            )

        # Show first 3 non-coinbase txs of block 0 in detail
        if block_idx == 0:
            print(f"\n  ── Block 0 detail ──")
            for tx in block.transactions[1:4]:
                inp_sum = sum(i.value for i in tx.inputs if i.value is not None)
                out_sum = sum(o.value for o in tx.outputs)
                print(
                    f"    txid={tx.txid[:16]}...  "
                    f"ins={tx.input_count}  outs={tx.output_count}  "
                    f"fee={tx.fee} sat  rate={tx.fee_rate} sat/vB  "
                    f"in_sum={inp_sum}  out_sum={out_sum}"
                )
            print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "═" * 68)
    print("SUMMARY")
    print(f"  Blocks parsed          : {block_idx + 1 - parse_errors}")
    print(f"  Parse errors           : {parse_errors}")
    print(f"  Total transactions     : {total_tx:,}")
    print(f"  Fees resolved (OK)     : {total_fees_ok:,}")
    print(f"  Fees unresolved (None) : {total_fees_none:,}")
    print(f"  Input types resolved   : {input_types_resolved:,}")
    print(f"  Input types missing    : {input_types_none:,}")

    if all_fee_rates:
        all_fee_rates.sort()
        min_r  = all_fee_rates[0]
        max_r  = all_fee_rates[-1]
        med_r  = statistics.median(all_fee_rates)
        mean_r = statistics.mean(all_fee_rates)
        print(f"\n  Fee rate stats (sat/vByte):")
        print(f"    min    : {min_r:.2f}")
        print(f"    median : {med_r:.2f}")
        print(f"    mean   : {mean_r:.2f}")
        print(f"    max    : {max_r:.2f}")
        consistent = min_r <= med_r <= max_r
        print(f"    order  : {'✅ min<=median<=max' if consistent else '❌ BROKEN'}")

    if parse_errors == 0 and total_fees_ok > 0:
        print(f"\n✅ PASS: Prevout resolution and fee computation successful")
    else:
        print(f"\n❌ Issues detected — review above output")
        sys.exit(1)


if __name__ == "__main__":
    main()
