"""
varint.py — Bitcoin CompactSize (VarInt) decoding.

Bitcoin uses "CompactSize" integers throughout the serialization format.
They encode integers of varying size into 1, 3, 5, or 9 bytes.

Encoding rules:
  value < 0xFD        → 1 byte  (value itself)
  value <= 0xFFFF     → 3 bytes (0xFD, then 2-byte LE)
  value <= 0xFFFFFFFF → 5 bytes (0xFE, then 4-byte LE)
  else                → 9 bytes (0xFF, then 8-byte LE)
"""

import struct


def read_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """
    Read a CompactSize integer from `data` starting at `offset`.

    Returns:
        (value, bytes_consumed)

    Raises:
        ValueError: if data is too short to decode.
    """
    if offset >= len(data):
        raise ValueError(
            f"Cannot read varint: offset {offset} >= data length {len(data)}"
        )

    first = data[offset]

    if first < 0xFD:
        return first, 1

    if first == 0xFD:
        if offset + 3 > len(data):
            raise ValueError("Truncated 2-byte varint")
        value = struct.unpack_from("<H", data, offset + 1)[0]
        return value, 3

    if first == 0xFE:
        if offset + 5 > len(data):
            raise ValueError("Truncated 4-byte varint")
        value = struct.unpack_from("<I", data, offset + 1)[0]
        return value, 5

    # 0xFF
    if offset + 9 > len(data):
        raise ValueError("Truncated 8-byte varint")
    value = struct.unpack_from("<Q", data, offset + 1)[0]
    return value, 9


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Alias for read_varint — returns (value, bytes_consumed)."""
    return read_varint(data, offset)
