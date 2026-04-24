"""
block.py — Parse a raw Bitcoin block payload into a ParsedBlock object.

A block payload (as yielded by block_file.iter_blocks) has this structure:

    [80 bytes] block header
    [varint]   transaction count
    [txs...]   serialized transactions

Block Header (80 bytes):
    [4B ] version
    [32B] prev_block_hash
    [32B] merkle_root
    [4B ] timestamp        (Unix)
    [4B ] bits             (compact difficulty target)
    [4B ] nonce

BIP34 Block Height:
    Since block 227,931 the coinbase scriptSig starts with a push of the
    block height as a little-endian integer:
        byte 0:    push length L (usually 0x03 for heights < 16M)
        bytes 1-L: height in little-endian

Reference:
    BIP34 — https://github.com/bitcoin/bips/blob/master/bip-0034.mediawiki
"""

from ..utils.hashing import double_sha256
from ..utils.io import read_bytes, read_uint32_le, read_int32_le
from ..utils.varint import decode_varint
from .transaction_model import ParsedBlock
from .transaction_parser import parse_transaction


# Minimum size of a block: 80-byte header + 1-byte varint tx count
BLOCK_HEADER_SIZE = 80


def _parse_block_header(data: bytes) -> dict:
    """
    Parse the 80-byte block header.

    Returns a dict with header fields and the computed block_hash.
    """
    assert len(data) >= BLOCK_HEADER_SIZE, (
        f"Block data too short: {len(data)} < {BLOCK_HEADER_SIZE}"
    )

    offset = 0
    version, offset = read_int32_le(data, offset)

    prev_hash_bytes, offset = read_bytes(data, offset, 32)
    prev_block_hash = prev_hash_bytes[::-1].hex()

    merkle_bytes, offset = read_bytes(data, offset, 32)
    merkle_root = merkle_bytes[::-1].hex()

    timestamp, offset = read_uint32_le(data, offset)
    bits, offset = read_uint32_le(data, offset)
    nonce, offset = read_uint32_le(data, offset)

    # Block hash = double-SHA256 of the raw 80-byte header, bytes reversed
    block_hash = double_sha256(data[:BLOCK_HEADER_SIZE])[::-1].hex()

    return {
        "version": version,
        "prev_block_hash": prev_block_hash,
        "merkle_root": merkle_root,
        "timestamp": timestamp,
        "bits": bits,
        "nonce": nonce,
        "block_hash": block_hash,
    }


def _decode_bip34_height(coinbase_script: bytes) -> int:
    """
    Decode block height from the coinbase scriptSig (BIP34).

    The coinbase scriptSig starts with a minimal script push:
        byte 0:    push length L (number of bytes encoding the height)
        bytes 1..L: block height as little-endian integer

    Returns 0 if the script is too short or malformed (pre-BIP34 blocks).

    Args:
        coinbase_script: Raw scriptSig bytes of the coinbase input.

    Returns:
        Block height as an integer, or 0 if not decodeable.
    """
    if len(coinbase_script) < 1:
        return 0

    push_len = coinbase_script[0]

    # push_len 0x00 = OP_0, heights 1-16 use OP_1..OP_16 (0x51-0x60)
    # Height bytes typically use 1-4 bytes for heights in the millions
    if push_len == 0 or push_len > 8:
        return 0

    if len(coinbase_script) < 1 + push_len:
        return 0

    height_bytes = coinbase_script[1: 1 + push_len]
    return int.from_bytes(height_bytes, byteorder="little")


def parse_block(block_bytes: bytes) -> ParsedBlock:
    """
    Parse a full Bitcoin block payload into a ParsedBlock object.

    Args:
        block_bytes: Raw block payload bytes (from iter_blocks, no magic prefix).

    Returns:
        ParsedBlock with header, all transactions, and decoded block height.

    Raises:
        ValueError: If the block data is too short or malformed.
    """
    if len(block_bytes) < BLOCK_HEADER_SIZE + 1:
        raise ValueError(
            f"Block too small: {len(block_bytes)} bytes "
            f"(minimum {BLOCK_HEADER_SIZE + 1})"
        )

    # ── Parse block header ────────────────────────────────────────────────────
    header = _parse_block_header(block_bytes)
    offset = BLOCK_HEADER_SIZE

    # ── Transaction count (varint) ────────────────────────────────────────────
    tx_count, vsize = decode_varint(block_bytes, offset)
    offset += vsize

    # ── Parse all transactions ────────────────────────────────────────────────
    transactions = []
    for i in range(tx_count):
        try:
            tx, offset = parse_transaction(block_bytes, offset)
            transactions.append(tx)
        except Exception as exc:
            raise ValueError(
                f"Failed to parse transaction {i} in block "
                f"{header['block_hash'][:16]}...: {exc}"
            ) from exc

    # ── Decode block height from coinbase (BIP34) ─────────────────────────────
    block_height = 0
    if transactions:
        coinbase_tx = transactions[0]
        if coinbase_tx.inputs and coinbase_tx.inputs[0].is_coinbase:
            block_height = _decode_bip34_height(coinbase_tx.inputs[0].script_sig)

    return ParsedBlock(
        block_hash=header["block_hash"],
        version=header["version"],
        prev_block_hash=header["prev_block_hash"],
        merkle_root=header["merkle_root"],
        timestamp=header["timestamp"],
        bits=header["bits"],
        nonce=header["nonce"],
        transactions=transactions,
        block_height=block_height,
    )
