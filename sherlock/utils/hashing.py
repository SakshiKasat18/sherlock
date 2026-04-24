"""
hashing.py — Bitcoin hashing utilities.

Bitcoin uses double-SHA256 for block hashes and transaction IDs,
and HASH160 (SHA256 + RIPEMD160) for address derivation.
"""

import hashlib
import struct


def double_sha256(data: bytes) -> bytes:
    """
    Compute double-SHA256: SHA256(SHA256(data)).

    This is the standard Bitcoin hash function used for:
      - Block hashes  (SHA256(SHA256(header)))
      - Transaction IDs (SHA256(SHA256(tx_bytes)))
    """
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def hash256_to_hex(data: bytes) -> str:
    """
    Compute double-SHA256 and return it in the standard Bitcoin
    display convention: little-endian bytes reversed to big-endian hex.

    Bitcoin displays hashes in reversed byte order (little-endian raw →
    big-endian display). This matches what block explorers show.

    Example:
        header_bytes → "000000000000000..."  (block hash)
    """
    return double_sha256(data)[::-1].hex()


def sha256(data: bytes) -> bytes:
    """Single SHA256 hash."""
    return hashlib.sha256(data).digest()


def hash160(data: bytes) -> bytes:
    """
    Compute HASH160: RIPEMD160(SHA256(data)).

    Used in P2PKH and P2SH address derivation.
    """
    sha = hashlib.sha256(data).digest()
    ripemd = hashlib.new("ripemd160")
    ripemd.update(sha)
    return ripemd.digest()


def decode_uint32_le(data: bytes) -> int:
    """Decode a 4-byte little-endian unsigned integer."""
    assert len(data) == 4, f"Expected 4 bytes, got {len(data)}"
    return struct.unpack("<I", data)[0]


def decode_uint64_le(data: bytes) -> int:
    """Decode an 8-byte little-endian unsigned integer."""
    assert len(data) == 8, f"Expected 8 bytes, got {len(data)}"
    return struct.unpack("<Q", data)[0]


def decode_int32_le(data: bytes) -> int:
    """Decode a 4-byte little-endian signed integer."""
    assert len(data) == 4, f"Expected 4 bytes, got {len(data)}"
    return struct.unpack("<i", data)[0]
