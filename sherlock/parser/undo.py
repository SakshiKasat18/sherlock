"""
undo.py — Bitcoin rev*.dat undo file parser (Phase 4).

rev*.dat files let Bitcoin Core reverse ("undo") a block.
Each record stores the UTXOs that were spent by a block's transactions,
so they can be restored during a chain reorganization.

Sherlock uses these records to recover the *input values* and
*scriptPubKeys* of spent UTXOs, which are not stored in blk*.dat.
Without this data, transaction fees, change detection, and most
heuristics cannot be computed.

File Structure (one rev*.dat record per block):
──────────────────────────────────────────────
[4 bytes] magic bytes     (0xF9 0xBE 0xB4 0xD9)
[4 bytes] payload size    (uint32 LE) — size of CBlockUndo record
[N bytes] CBlockUndo      — undo data for the block
[32 bytes] checksum       — double-SHA256 of the CBlockUndo bytes

CBlockUndo = vector<CTxUndo>
    [varint] num_tx_undos   (= block.tx_count - 1, coinbase excluded)
    [CTxUndo * num_tx_undos]

CTxUndo = vector<CTxInUndo>
    [varint] num_inputs
    [CTxInUndo * num_inputs]

CTxInUndo = spent UTXO info
    [Bitcoin-varint] height_code   = 2 * height + (1 if coinbase output)
    [Bitcoin-varint] nVersion      (only if height > 0, i.e., not genesis)
    [CompressedScript]             scriptPubKey in compressed form
    [CompressedAmount]             value in compressed form

CompressedAmount:
    Special integer encoding: see decompress_amount() below.
    Returns value in satoshis.

CompressedScript prefix byte:
    0x00        → P2PKH (20 bytes hash follows)
    0x01        → P2SH  (20 bytes hash follows)
    0x02, 0x03  → P2PK compressed pubkey (32 bytes follows, prefix reconstructed)
    0x04, 0x05  → P2PK uncompressed pubkey (32 bytes follows)
    n + 6       → raw script (n bytes follow)

References:
    Bitcoin Core: src/undo.h, src/compressor.h, src/compressor.cpp
    Bitcoin StackExchange: https://bitcoin.stackexchange.com/q/111355
"""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..utils.varint import decode_varint
from ..utils.io import read_bytes, read_uint32_le
from ..utils.hashing import double_sha256
from .script import classify_script
from .transaction_model import ParsedBlock, ParsedTransaction


# ── Magic bytes and file constants ───────────────────────────────────────────
MAINNET_MAGIC = b"\xf9\xbe\xb4\xd9"
CHECKSUM_SIZE = 32  # double-SHA256 checksum appended to each CBlockUndo


# ── Data containers ───────────────────────────────────────────────────────────

@dataclass
class TxInUndo:
    """The spent UTXO info recovered from one CTxInUndo entry."""
    height: int
    is_coinbase_output: bool    # True if this UTXO was created by a coinbase tx
    value: int                  # satoshis
    script_pubkey: bytes        # full reconstructed scriptPubKey


@dataclass
class TxUndo:
    """Undo data for one transaction (list of its spent inputs)."""
    inputs: list[TxInUndo]


@dataclass
class BlockUndo:
    """Undo data for one full block (excludes coinbase)."""
    tx_undos: list[TxUndo]


# ── CompressedAmount decompressor ──────────────────────────────────────────────

def _read_bitcoin_varint(data: bytes, offset: int) -> tuple[int, int]:
    """
    Read Bitcoin Core's *internal* varint format used in undo files.

    This is DIFFERENT from the CompactSize (protocol varint) used in block
    serialization. This encoding is used in LevelDB and undo files.

    Encoding: each byte contributes 7 bits; the MSB signals continuation.
    Non-minimal: value is decoded as: n = sum((byte & 0x7F) << shift).

    Returns:
        (value, bytes_consumed)
    """
    n = 0
    pos = offset
    while True:
        if pos >= len(data):
            raise ValueError(
                f"Truncated bitcoin-varint at offset {pos}"
            )
        byte = data[pos]
        pos += 1
        n = (n << 7) | (byte & 0x7F)
        if byte & 0x80 == 0:
            return n, pos - offset
        n += 1  # Adjustment for the non-minimal encoding


def decompress_amount(x: int) -> int:
    """
    Decompress a Bitcoin Core compressed amount back to satoshis.

    Bitcoin Core compresses amounts to save space in undo files and LevelDB.
    This is the inverse of CompressAmount() from src/compressor.cpp.

    Encoding trick: small amounts (common) use fewer bytes.
    Formula:
        if x == 0: return 0
        x -= 1
        e = x % 10; x //= 10
        if e < 9:
            d = x % 9 + 1; x //= 9; n = x * 10 + d
        else:
            n = x + 1
        return n * 10**e

    Args:
        x: The compressed amount integer (from bitcoin-varint in undo data).

    Returns:
        int: Amount in satoshis (1 BTC = 100,000,000 satoshis).
    """
    if x == 0:
        return 0
    x -= 1
    e = x % 10
    x //= 10
    if e < 9:
        d = x % 9 + 1
        x //= 9
        n = x * 10 + d
    else:
        n = x + 1
    return n * (10 ** e)


def _decompress_script(data: bytes, offset: int) -> tuple[bytes, int]:
    """
    Decompress a Bitcoin Core CompressedScript back to a full scriptPubKey.

    The first field is `nSize`, read as a CompactSize integer.
    nSize determines both the type and how many following bytes contain the data:

        nSize == 0:  P2PKH — 20 bytes of key hash follow
                     → OP_DUP OP_HASH160 <20B> OP_EQUALVERIFY OP_CHECKSIG
        nSize == 1:  P2SH — 20 bytes of script hash follow
                     → OP_HASH160 <20B> OP_EQUAL
        nSize == 2:  P2PK compressed (prefix 0x02) — 32 bytes X follow
        nSize == 3:  P2PK compressed (prefix 0x03) — 32 bytes X follow
        nSize == 4:  P2PK uncompressed (even Y) — 32 bytes X follow
        nSize == 5:  P2PK uncompressed (odd Y) — 32 bytes X follow
        nSize >= 6:  Raw script — (nSize - 6) bytes follow

    Source: Bitcoin Core src/compressor.cpp DecompressScript() + GetSpecialScriptSize()

    Returns:
        (reconstructed_script_pubkey_bytes, new_offset)
    """
    if offset >= len(data):
        raise ValueError(f"Cannot read CompressedScript at offset {offset}")

    # nSize is a CompactSize integer (same protocol format as blk*.dat)
    nsize, n = decode_varint(data, offset)
    offset += n

    if nsize == 0:
        # P2PKH: OP_DUP OP_HASH160 <20B> OP_EQUALVERIFY OP_CHECKSIG
        hash20, offset = read_bytes(data, offset, 20)
        return bytes([0x76, 0xa9, 0x14]) + hash20 + bytes([0x88, 0xac]), offset

    if nsize == 1:
        # P2SH: OP_HASH160 <20B> OP_EQUAL
        hash20, offset = read_bytes(data, offset, 20)
        return bytes([0xa9, 0x14]) + hash20 + bytes([0x87]), offset

    if nsize in (2, 3):
        # Compressed P2PK: 33-byte script with prefix byte = nsize
        x_bytes, offset = read_bytes(data, offset, 32)
        pubkey = bytes([nsize]) + x_bytes
        return bytes([0x21]) + pubkey + bytes([0xac]), offset

    if nsize in (4, 5):
        # Uncompressed P2PK stored as 32-byte X; nsize=4→even Y (0x02), 5→odd (0x03)
        x_bytes, offset = read_bytes(data, offset, 32)
        prefix = 0x02 if nsize == 4 else 0x03
        pubkey = bytes([prefix]) + x_bytes
        return bytes([0x21]) + pubkey + bytes([0xac]), offset

    # nsize >= 6: arbitrary raw script; raw byte count = nsize - 6
    raw_len = nsize - 6
    script_bytes, offset = read_bytes(data, offset, raw_len)
    return script_bytes, offset


# ── CTxInUndo parser ──────────────────────────────────────────────────────────

def _parse_txin_undo(data: bytes, offset: int) -> tuple[TxInUndo, int]:
    """
    Parse one CTxInUndo entry (spent UTXO record).

    Format from Bitcoin Core src/undo.h TxInUndoFormatter::Unser():
        [bitcoin-varint] height_code  = 2*height + (1 if coinbase)
        [bitcoin-varint] nVersionDummy (only present if height > 0)
        [TxOutCompression]
            [bitcoin-varint] CompressedAmount   ← AMOUNT FIRST
            [CompressedScript]                  ← SCRIPT SECOND

    IMPORTANT: TxOutCompression serializes Amount before Script.

    Returns:
        (TxInUndo, new_offset)
    """
    # ── height + coinbase flag ────────────────────────────────────────────────
    height_code, n = _read_bitcoin_varint(data, offset)
    offset += n

    height = height_code >> 1
    is_coinbase_output = bool(height_code & 1)

    # ── nVersionDummy (skip — legacy compatibility field) ─────────────────────
    # Only present when height > 0 (per Bitcoin Core compatibility comment).
    if height > 0:
        _nversion, n = _read_bitcoin_varint(data, offset)
        offset += n

    # ── TxOutCompression: Amount FIRST, then Script ───────────────────────────
    # From Bitcoin Core src/compressor.h TxOutCompression:
    #   READWRITE(Using<AmountCompression>(txout.nValue));
    #   READWRITE(Using<ScriptCompression>(txout.scriptPubKey));
    compressed_amount, n = _read_bitcoin_varint(data, offset)
    offset += n
    value = decompress_amount(compressed_amount)

    # ── CompressedScript → full scriptPubKey ──────────────────────────────────
    script_pubkey, offset = _decompress_script(data, offset)

    return TxInUndo(
        height=height,
        is_coinbase_output=is_coinbase_output,
        value=value,
        script_pubkey=script_pubkey,
    ), offset


# ── CTxUndo parser ────────────────────────────────────────────────────────────

def _parse_tx_undo(data: bytes, offset: int) -> tuple[TxUndo, int]:
    """
    Parse one CTxUndo record (vector of CTxInUndo).

    Each non-coinbase transaction has one CTxUndo, with one CTxInUndo per input.

    Returns:
        (TxUndo, new_offset)
    """
    input_count, n = decode_varint(data, offset)
    offset += n

    inputs: list[TxInUndo] = []
    for _ in range(input_count):
        txin_undo, offset = _parse_txin_undo(data, offset)
        inputs.append(txin_undo)

    return TxUndo(inputs=inputs), offset


# ── CBlockUndo parser ─────────────────────────────────────────────────────────

def _parse_block_undo_payload(data: bytes) -> BlockUndo:
    """
    Parse a CBlockUndo payload (the bytes between magic/size and checksum).

    CBlockUndo = vector<CTxUndo>, one per non-coinbase transaction.

    Args:
        data: Raw CBlockUndo bytes (without magic, size, or checksum).

    Returns:
        BlockUndo with one TxUndo per non-coinbase transaction.
    """
    tx_count, n = decode_varint(data, 0)
    offset = n

    tx_undos: list[TxUndo] = []
    for i in range(tx_count):
        tx_undo, offset = _parse_tx_undo(data, offset)
        tx_undos.append(tx_undo)

    return BlockUndo(tx_undos=tx_undos)


# ── Rev file loader ───────────────────────────────────────────────────────────

def load_undo_file(path: str | Path, xor_key: bytes) -> list[BlockUndo]:
    """
    Load and parse a complete rev*.dat file.

    Returns one BlockUndo per block record found in the file.
    Records appear in the same order as blocks in the matching blk*.dat file.

    The rev*.dat file uses the same magic-byte + size format as blk*.dat,
    plus a 32-byte checksum after each CBlockUndo payload.

    Args:
        path:    Path to the rev*.dat file.
        xor_key: 8-byte XOR key from xor.dat.

    Returns:
        List[BlockUndo] — one entry per block, in file order.
    """
    from .block_file import xor_decode  # late import to avoid circular

    path = Path(path)
    raw = path.read_bytes()

    # XOR-decode the entire file (fast for rev files which are typically < 15 MB)
    from .xor import xor_decode as _xor_decode
    data = _xor_decode(raw, xor_key, file_offset=0)

    file_size = len(data)
    offset = 0
    block_undos: list[BlockUndo] = []

    while offset < file_size - 8:
        # ── Magic bytes ───────────────────────────────────────────────────────
        magic = data[offset: offset + 4]
        if magic != MAINNET_MAGIC:
            offset += 1
            continue
        offset += 4

        # ── Payload size ──────────────────────────────────────────────────────
        if offset + 4 > file_size:
            break
        size = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if size == 0 or offset + size + CHECKSUM_SIZE > file_size:
            break

        # ── CBlockUndo payload ────────────────────────────────────────────────
        payload = data[offset: offset + size]
        offset += size

        # ── 32-byte checksum (skip — we trust the data) ───────────────────────
        offset += CHECKSUM_SIZE

        try:
            block_undo = _parse_block_undo_payload(payload)
            block_undos.append(block_undo)
        except Exception as exc:
            # Don't silently swallow — append empty and log to stderr
            import sys
            print(f"[undo] Warning: block undo parse failed: {exc}", file=sys.stderr)
            block_undos.append(BlockUndo(tx_undos=[]))

    return block_undos


# ── Prevout resolution ────────────────────────────────────────────────────────

def resolve_prevouts(block: ParsedBlock, block_undo: BlockUndo) -> None:
    """
    Populate ParsedInput.value, .script_pubkey, .script_type for each
    non-coinbase transaction input in a block.

    Mapping:
        block.transactions[1:]           → block_undo.tx_undos (1:1)
        tx.inputs[j]                     → tx_undo.inputs[j]  (1:1)

    Coinbase transaction (index 0) is ALWAYS skipped — it has no prevouts.

    After resolution, compute fee and fee_rate for each non-coinbase tx:
        fee      = sum(input.value for each input) - sum(output.value)
        fee_rate = fee / tx.vsize   (rounded to 2 decimal places)

    If resolution fails for a transaction (e.g., undo data missing),
    that tx's fee remains None — no crash.

    Args:
        block:      A fully parsed block (from block.py::parse_block).
        block_undo: The corresponding BlockUndo (from load_undo_file).

    Modifies:
        ParsedInput.value, .script_pubkey, .script_type (in-place)
        ParsedTransaction.fee, .fee_rate (in-place)
    """
    # Skip coinbase (tx index 0); undo data covers transactions[1:]
    non_coinbase_txs = block.transactions[1:]
    tx_undos = block_undo.tx_undos

    # Undo record count should match non-coinbase tx count.
    # If there's a mismatch, process only what we have.
    pairs = zip(non_coinbase_txs, tx_undos)

    for tx, tx_undo in pairs:
        try:
            _resolve_single_tx(tx, tx_undo)
        except Exception:
            # Prevout resolution failed — fee stays None, don't crash
            pass


def _resolve_single_tx(tx: ParsedTransaction, tx_undo: TxUndo) -> None:
    """
    Resolve prevouts for one transaction and compute its fee.

    Args:
        tx:       ParsedTransaction to update (in-place).
        tx_undo:  Corresponding TxUndo from rev*.dat.
    """
    if len(tx.inputs) != len(tx_undo.inputs):
        # Input count mismatch — skip this tx to avoid mis-mapping
        return

    for inp, txin_undo in zip(tx.inputs, tx_undo.inputs):
        inp.value = txin_undo.value
        inp.script_pubkey = txin_undo.script_pubkey
        inp.script_type = classify_script(txin_undo.script_pubkey)

    # Compute fee if all inputs have values
    input_values = [inp.value for inp in tx.inputs if inp.value is not None]
    if len(input_values) == len(tx.inputs):
        total_in = sum(input_values)
        total_out = sum(o.value for o in tx.outputs)
        fee = total_in - total_out
        # Guard against negative fees (shouldn't happen but be safe)
        if fee >= 0:
            tx.fee = fee
            tx.fee_rate = round(fee / tx.vsize, 2) if tx.vsize > 0 else 0.0
