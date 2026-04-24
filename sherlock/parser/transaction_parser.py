"""
transaction_parser.py — SegWit-aware Bitcoin transaction binary parser.

Parses one serialized transaction from a bytes buffer and returns a
ParsedTransaction object. No state is held — all functions are pure.

IMPORTANT — SegWit serialization layout:
    [4B  ] version
    [1B  ] marker = 0x00   ← SegWit only
    [1B  ] flag   = 0x01   ← SegWit only
    [var ] input count
    [var ] inputs
    [var ] output count
    [var ] outputs
    [var ] witness data (per input, SegWit only)
    [4B  ] locktime

TXID calculation:
    The txid is the double-SHA256 of the LEGACY (non-witness) serialization.
    For SegWit transactions we must strip the marker, flag, and witness fields
    before hashing. This is done by re-serializing without them.

References:
    BIP141 — Segregated Witness
    https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki
"""

import math
from typing import Optional

from ..utils.varint import decode_varint
from ..utils.hashing import double_sha256
from ..utils.io import (
    read_bytes,
    read_uint8,
    read_uint32_le,
    read_int32_le,
    read_uint64_le,
)
from .script import classify_script
from .transaction_model import ParsedInput, ParsedOutput, ParsedTransaction


# SegWit marker/flag bytes that follow the version field
SEGWIT_MARKER = 0x00
SEGWIT_FLAG = 0x01


def _parse_input(data: bytes, offset: int) -> tuple[ParsedInput, int]:
    """
    Parse one transaction input starting at `offset`.

    Input serialization:
        [32B] prev_txid   (reversed bytes = txid in display form)
        [4B ] prev_vout   (uint32 LE — 0xFFFFFFFF for coinbase)
        [var] script_sig_len
        [N  ] script_sig
        [4B ] sequence    (uint32 LE)

    Returns:
        (ParsedInput, new_offset)
    """
    # prev_txid — 32 bytes stored little-endian, displayed reversed
    txid_bytes, offset = read_bytes(data, offset, 32)
    prev_txid = txid_bytes[::-1].hex()

    # prev_vout — 4 bytes LE
    prev_vout, offset = read_uint32_le(data, offset)

    # scriptSig — variable length
    script_len, vsize = decode_varint(data, offset)
    offset += vsize
    script_sig, offset = read_bytes(data, offset, script_len)

    # sequence — 4 bytes LE
    sequence, offset = read_uint32_le(data, offset)

    inp = ParsedInput(
        prev_txid=prev_txid,
        prev_vout=prev_vout,
        script_sig=script_sig,
        sequence=sequence,
    )
    return inp, offset


def _parse_output(data: bytes, offset: int, index: int) -> tuple[ParsedOutput, int]:
    """
    Parse one transaction output starting at `offset`.

    Output serialization:
        [8B ] value         (uint64 LE, satoshis)
        [var] script_pubkey_len
        [N  ] script_pubkey

    Returns:
        (ParsedOutput, new_offset)
    """
    value, offset = read_uint64_le(data, offset)

    script_len, vsize = decode_varint(data, offset)
    offset += vsize
    script_pubkey, offset = read_bytes(data, offset, script_len)

    script_type = classify_script(script_pubkey)

    out = ParsedOutput(
        index=index,
        value=value,
        script_pubkey=script_pubkey,
        script_type=script_type,
    )
    return out, offset


def _parse_witness_for_input(data: bytes, offset: int) -> tuple[list[bytes], int]:
    """
    Parse the witness stack for one input.

    Witness serialization (one per input, appears after all outputs):
        [var] item_count
        For each item:
            [var] item_length
            [N  ] item_bytes

    Returns:
        (list_of_witness_items, new_offset)
    """
    item_count, vsize = decode_varint(data, offset)
    offset += vsize

    items: list[bytes] = []
    for _ in range(item_count):
        item_len, vsize = decode_varint(data, offset)
        offset += vsize
        item, offset = read_bytes(data, offset, item_len)
        items.append(item)

    return items, offset


def _compute_txid(data: bytes, is_segwit: bool,
                  segwit_start: int, offset_after_outputs: int,
                  total_end: int) -> str:
    """
    Compute the txid (double-SHA256 of non-witness serialization).

    For legacy transactions:
        txid = double_sha256(data[start:end])

    For SegWit transactions:
        txid = double_sha256(legacy_serialization)
        where legacy_serialization strips:
            - the 2-byte marker+flag (bytes at segwit_start..segwit_start+2)
            - the witness data (bytes from offset_after_outputs to locktime)

    Args:
        data:                 Full raw transaction bytes (start to locktime+4).
        is_segwit:            Whether this is a SegWit transaction.
        segwit_start:         Offset of the 0x00 marker byte (= version_end).
        offset_after_outputs: Offset immediately after the last output
                              (= start of witness data or locktime).
        total_end:            Offset past the locktime (end of tx).

    Returns:
        Hex64 txid string.
    """
    if not is_segwit:
        raw = data[:total_end]
    else:
        # Re-serialize without SegWit marker (2 bytes) and witness data
        # Segment layout:
        #   [version 4B] [marker 1B] [flag 1B] [inputs+outputs] [witness] [locktime 4B]
        # Strip marker+flag (skip segwit_start..segwit_start+2)
        # Strip witness (skip offset_after_outputs..total_end-4)
        legacy_payload = (
            data[:segwit_start]                       # version
            + data[segwit_start + 2: offset_after_outputs]  # inputs + outputs
            + data[total_end - 4: total_end]          # locktime
        )
        raw = legacy_payload

    return double_sha256(raw)[::-1].hex()


def _compute_vsize(
    total_size: int,
    is_segwit: bool,
    segwit_start: int,
    offset_after_outputs: int,
) -> tuple[int, int]:
    """
    Compute transaction weight and virtual size (vsize).

    Bitcoin weight formula (BIP141):
        weight = base_size * 3 + total_size
        vsize  = ceil(weight / 4)

    base_size = total_size - marker(1) - flag(1) - witness_size
    witness_size = total_size - offset_after_outputs - 4  (minus locktime)

    For legacy (non-SegWit):
        weight = total_size * 4
        vsize  = total_size

    Returns:
        (weight, vsize)
    """
    if not is_segwit:
        return total_size * 4, total_size

    # Size of just the witness data (between outputs and locktime)
    witness_size = total_size - offset_after_outputs - 4
    # Strip: 2-byte marker+flag + witness
    stripped_size = total_size - 2 - witness_size
    weight = stripped_size * 3 + total_size
    vsize = math.ceil(weight / 4)
    return weight, vsize


def parse_transaction(data: bytes, offset: int = 0) -> tuple[ParsedTransaction, int]:
    """
    Parse one complete Bitcoin transaction from `data` starting at `offset`.

    Handles both legacy and SegWit (BIP141) transactions.

    Args:
        data:   Raw bytes buffer containing the transaction.
        offset: Starting byte position within `data`.

    Returns:
        (ParsedTransaction, new_offset)

    Raises:
        ValueError: If the transaction cannot be parsed (truncated data).
    """
    tx_start = offset

    # ── Version (4 bytes, signed int32 LE) ──────────────────────────────────
    version, offset = read_int32_le(data, offset)

    # ── SegWit detection: peek at next 2 bytes ───────────────────────────────
    # If bytes are [0x00, 0x01] immediately after version → SegWit tx.
    segwit_marker_pos = offset
    is_segwit = (
        offset + 2 <= len(data)
        and data[offset] == SEGWIT_MARKER
        and data[offset + 1] == SEGWIT_FLAG
    )
    if is_segwit:
        offset += 2  # Consume marker + flag

    # ── Inputs ──────────────────────────────────────────────────────────────
    input_count, vsize = decode_varint(data, offset)
    offset += vsize

    inputs: list[ParsedInput] = []
    for _ in range(input_count):
        inp, offset = _parse_input(data, offset)
        inputs.append(inp)

    # ── Outputs ─────────────────────────────────────────────────────────────
    output_count, vsize = decode_varint(data, offset)
    offset += vsize

    outputs: list[ParsedOutput] = []
    for i in range(output_count):
        out, offset = _parse_output(data, offset, index=i)
        outputs.append(out)

    # Record position after outputs (needed for weight/txid calculation)
    offset_after_outputs = offset

    # ── Witness data (SegWit only) ────────────────────────────────────────────
    # One witness stack per input, in the same order as the inputs.
    if is_segwit:
        for inp in inputs:
            witnesses, offset = _parse_witness_for_input(data, offset)
            inp.witnesses = witnesses

    # ── Locktime (4 bytes LE) ────────────────────────────────────────────────
    locktime, offset = read_uint32_le(data, offset)

    tx_end = offset
    total_size = tx_end - tx_start

    # ── TXID and weight ──────────────────────────────────────────────────────
    tx_data = data[tx_start:tx_end]
    txid = _compute_txid(
        tx_data,
        is_segwit=is_segwit,
        segwit_start=segwit_marker_pos - tx_start,
        offset_after_outputs=offset_after_outputs - tx_start,
        total_end=total_size,
    )
    weight, vsize_val = _compute_vsize(
        total_size=total_size,
        is_segwit=is_segwit,
        segwit_start=segwit_marker_pos - tx_start,
        offset_after_outputs=offset_after_outputs - tx_start,
    )

    tx = ParsedTransaction(
        txid=txid,
        version=version,
        inputs=inputs,
        outputs=outputs,
        locktime=locktime,
        is_segwit=is_segwit,
        size=total_size,
        vsize=vsize_val,
        weight=weight,
    )
    return tx, tx_end
