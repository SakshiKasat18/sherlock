"""
io.py — Low-level binary read helpers.

These helpers wrap common struct read patterns used across parsers.
All reads take a `data: bytes` buffer and an `offset: int`, and
return `(value, new_offset)` so callers can chain reads cleanly.
"""

import struct
from typing import Any


def read_bytes(data: bytes, offset: int, n: int) -> tuple[bytes, int]:
    """
    Read exactly `n` bytes from `data[offset:]`.

    Returns:
        (bytes_slice, offset + n)

    Raises:
        ValueError: if there are fewer than `n` bytes available.
    """
    end = offset + n
    if end > len(data):
        raise ValueError(
            f"read_bytes: need {n} bytes at offset {offset}, "
            f"but only {len(data) - offset} available"
        )
    return data[offset:end], end


def read_uint8(data: bytes, offset: int) -> tuple[int, int]:
    """Read 1 unsigned byte. Returns (value, offset+1)."""
    if offset >= len(data):
        raise ValueError(f"read_uint8: offset {offset} out of range")
    return data[offset], offset + 1


def read_uint16_le(data: bytes, offset: int) -> tuple[int, int]:
    """Read 2-byte little-endian uint16. Returns (value, offset+2)."""
    raw, new_off = read_bytes(data, offset, 2)
    return struct.unpack_from("<H", raw)[0], new_off


def read_uint32_le(data: bytes, offset: int) -> tuple[int, int]:
    """Read 4-byte little-endian uint32. Returns (value, offset+4)."""
    raw, new_off = read_bytes(data, offset, 4)
    return struct.unpack_from("<I", raw)[0], new_off


def read_int32_le(data: bytes, offset: int) -> tuple[int, int]:
    """Read 4-byte little-endian int32 (signed). Returns (value, offset+4)."""
    raw, new_off = read_bytes(data, offset, 4)
    return struct.unpack_from("<i", raw)[0], new_off


def read_uint64_le(data: bytes, offset: int) -> tuple[int, int]:
    """Read 8-byte little-endian uint64. Returns (value, offset+8)."""
    raw, new_off = read_bytes(data, offset, 8)
    return struct.unpack_from("<Q", raw)[0], new_off


def read_hash(data: bytes, offset: int) -> tuple[str, int]:
    """
    Read a 32-byte hash and return it in Bitcoin display convention:
    bytes are reversed (little-endian → big-endian display) and hex-encoded.

    Returns:
        (hex_string_64_chars, offset+32)
    """
    raw, new_off = read_bytes(data, offset, 32)
    return raw[::-1].hex(), new_off
