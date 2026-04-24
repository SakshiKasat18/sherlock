"""
tests/test_units.py — Pure unit tests requiring no fixture files.

These tests cover deterministic logic only — no filesystem access, no large
binary files. They run in CI (GitHub Actions) on every push.

Full integration tests (test_block_parsing, test_heuristics, etc.) require
the fixtures/ directory and are run locally via: make test
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sherlock.utils.varint import read_varint
from sherlock.parser.script import classify_script
from sherlock.heuristics.engine import HEURISTICS, run_heuristics, classify_transaction
from sherlock.parser.transaction_model import ParsedTransaction, ParsedInput, ParsedOutput


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_input(script_type="p2wpkh", value=100_000,
                script_pubkey=None) -> ParsedInput:
    return ParsedInput(
        prev_txid    = "ab" * 32,
        prev_vout    = 0,
        script_sig   = b"",
        sequence     = 0xFFFFFFFF,
        witnesses    = [],
        value        = value,
        script_pubkey= script_pubkey or (b"\x00\x14" + b"\xab" * 20),
        script_type  = script_type,
    )


def _make_output(value=50_000, script_type="p2wpkh",
                 script_pubkey=None) -> ParsedOutput:
    return ParsedOutput(
        index        = 0,
        value        = value,
        script_pubkey= script_pubkey or (b"\x00\x14" + b"\xcd" * 20),
        script_type  = script_type,
    )


def _make_tx(inputs=None, outputs=None) -> ParsedTransaction:
    return ParsedTransaction(
        txid        = "aa" * 32,
        version     = 1,
        inputs      = inputs  or [],
        outputs     = outputs or [],
        locktime    = 0,
        is_segwit   = False,
        size        = 250,
        vsize       = 250,
        weight      = 1000,
    )


# ── Test runner ───────────────────────────────────────────────────────────────

_passed = []
_failed = []

def check(label, cond):
    if cond:
        _passed.append(label)
        print(f"  ✅  {label}")
    else:
        _failed.append(label)
        print(f"  ❌  {label}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_varint():
    """read_varint(data, offset) → (value, bytes_consumed)."""
    v, n = read_varint(b"\x00", 0)
    check("varint 0x00 == 0, consumed 1",    v == 0  and n == 1)

    v, n = read_varint(b"\xfc", 0)
    check("varint 0xFC == 252, consumed 1",  v == 252 and n == 1)

    v, n = read_varint(b"\xfd\x00\x01", 0)
    check("varint 0xFD prefix == 256, consumed 3", v == 256 and n == 3)

    v, n = read_varint(b"\xfe\x01\x00\x00\x00", 0)
    check("varint 0xFE prefix == 1, consumed 5",   v == 1 and n == 5)


def test_classify_script():
    """classify_script identifies common script types from raw bytes."""
    check("P2WPKH", classify_script(b"\x00\x14" + b"\xab" * 20) == "p2wpkh")
    check("P2TR",   classify_script(b"\x51\x20" + b"\xcd" * 32) == "p2tr")
    check("P2PKH",  classify_script(
        b"\x76\xa9\x14" + b"\xef" * 20 + b"\x88\xac") == "p2pkh")
    check("OP_RETURN", classify_script(b"\x6a\x04" + b"\x00" * 4) == "op_return")
    check("unknown",   classify_script(b"\xff\xff\xff") == "unknown")


def test_cioh_heuristic():
    """CIOH fires on multi-input transactions, not on single-input."""
    cioh = next(h for h in HEURISTICS if h.ID == "cioh")

    tx_multi = _make_tx(
        inputs=[_make_input(), _make_input()],
        outputs=[_make_output()],
    )
    r = cioh.analyze(tx_multi)
    check("CIOH detected on 2-input tx",    r["detected"] is True)
    check("CIOH confidence present",         "confidence" in r)

    tx_single = _make_tx(inputs=[_make_input()], outputs=[_make_output()])
    r2 = cioh.analyze(tx_single)
    check("CIOH not detected on 1-input tx", r2["detected"] is False)


def test_coinjoin_heuristic():
    """CoinJoin fires on ≥3 inputs with equal-value outputs."""
    cj = next(h for h in HEURISTICS if h.ID == "coinjoin")

    # 3 inputs (required) + 3 equal-value outputs → CoinJoin
    tx_cj = _make_tx(
        inputs=[_make_input(), _make_input(), _make_input()],
        outputs=[_make_output(50_000), _make_output(50_000), _make_output(50_000)],
    )
    check("CoinJoin detected on equal-value outputs", cj.analyze(tx_cj)["detected"] is True)

    # Only 2 inputs → short-circuits before checking outputs
    tx_no = _make_tx(
        inputs=[_make_input(), _make_input()],
        outputs=[_make_output(50_000), _make_output(50_000), _make_output(50_000)],
    )
    check("CoinJoin not on <3 inputs", cj.analyze(tx_no)["detected"] is False)


def test_consolidation_heuristic():
    """Consolidation fires on many-input / 1-output transactions."""
    cons = next(h for h in HEURISTICS if h.ID == "consolidation")

    tx = _make_tx(
        inputs=[_make_input() for _ in range(6)],
        outputs=[_make_output(500_000)],
    )
    check("Consolidation: 6 inputs → 1 output", cons.analyze(tx)["detected"] is True)

    tx_no = _make_tx(inputs=[_make_input()], outputs=[_make_output(), _make_output()])
    check("Consolidation not on 1-input tx",    cons.analyze(tx_no)["detected"] is False)


def test_run_heuristics_schema():
    """run_heuristics always returns all heuristic keys, detected or not."""
    tx = _make_tx(inputs=[_make_input()], outputs=[_make_output()])
    results = run_heuristics(tx)

    expected_keys = {h.ID for h in HEURISTICS}
    check("All heuristic keys present",  set(results.keys()) == expected_keys)
    check("Each result has 'detected'",
          all("detected" in v for v in results.values()))


def test_classify_transaction():
    """classify_transaction maps heuristic dicts to correct labels."""
    def _r(detected_keys):
        return {h.ID: {"detected": h.ID in detected_keys} for h in HEURISTICS}

    check("coinjoin wins over all",
          classify_transaction(_r({"coinjoin", "cioh"})) == "coinjoin")
    check("consolidation second",
          classify_transaction(_r({"consolidation", "cioh"})) == "consolidation")
    check("batch_payment third",
          classify_transaction(_r({"batch_payment"})) == "batch_payment")
    check("simple_payment on cioh only",
          classify_transaction(_r({"cioh"})) == "simple_payment")
    check("unknown when nothing fires",
          classify_transaction(_r(set())) == "unknown")


def test_address_reuse_heuristic():
    """Address reuse fires when the same scriptPubKey is in both input and output."""
    reuse = next(h for h in HEURISTICS if h.ID == "address_reuse")
    shared = b"\x00\x14" + b"\xaa" * 20

    tx = _make_tx(
        inputs =[_make_input(script_pubkey=shared)],
        outputs=[_make_output(script_pubkey=shared),
                 _make_output(script_pubkey=b"\x00\x14" + b"\xbb" * 20)],
    )
    check("Address reuse detected", reuse.analyze(tx)["detected"] is True)

    tx_no = _make_tx(
        inputs =[_make_input(script_pubkey=b"\x00\x14" + b"\xcc" * 20)],
        outputs=[_make_output(script_pubkey=b"\x00\x14" + b"\xdd" * 20)],
    )
    check("Address reuse not on distinct scripts", reuse.analyze(tx_no)["detected"] is False)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("\nSherlock — unit tests (no fixtures required)")
    print("─" * 55)

    test_varint()
    print()
    test_classify_script()
    print()
    test_cioh_heuristic()
    print()
    test_coinjoin_heuristic()
    print()
    test_consolidation_heuristic()
    print()
    test_run_heuristics_schema()
    print()
    test_classify_transaction()
    print()
    test_address_reuse_heuristic()

    print("\n" + "─" * 55)
    print(f"  {len(_passed)} passed  |  {len(_failed)} failed\n")

    if _failed:
        for f in _failed:
            print(f"  ❌  {f}")
        sys.exit(1)
    else:
        print("✅  All unit tests passed")


if __name__ == "__main__":
    main()
