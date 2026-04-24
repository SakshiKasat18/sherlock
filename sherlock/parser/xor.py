"""
xor.py — XOR key loading and block file decoding.

Bitcoin Core (v28+) stores blk*.dat and rev*.dat XOR-encrypted
using an 8-byte key stored in blocks/xor.dat.

XOR Algorithm:
    decoded_byte[i] = file_byte[i] ^ key[(file_offset + i) % 8]

The key is applied at the raw file offset level, meaning the offset
counter is continuous across the entire file — not per-block.

If xor.dat contains all zero bytes (null key), the files are
stored unencoded (no XOR applied — XOR with 0 is identity).

Reference:
    Bitcoin Core: src/util/fs.h XORBytes()
    Test: test/functional/feature_blocksxor.py
"""


XOR_KEY_SIZE = 8  # Bitcoin Core always uses an 8-byte XOR key


def load_xor_key(path: str) -> bytes:
    """
    Load the 8-byte XOR key from xor.dat.

    Args:
        path: Path to the xor.dat file.

    Returns:
        bytes: The 8-byte XOR key.

    Raises:
        FileNotFoundError: if xor.dat does not exist.
        ValueError: if xor.dat is not exactly 8 bytes.
    """
    with open(path, "rb") as f:
        key = f.read()

    if len(key) != XOR_KEY_SIZE:
        raise ValueError(
            f"xor.dat must be exactly {XOR_KEY_SIZE} bytes, "
            f"got {len(key)} bytes at '{path}'"
        )

    return key


def is_null_key(key: bytes) -> bool:
    """Return True if the XOR key is all zeros (no encoding applied)."""
    return all(b == 0 for b in key)


def xor_decode(data: bytes, key: bytes, file_offset: int = 0) -> bytes:
    """
    XOR-decode a chunk of data using the 8-byte rolling key.

    The key is applied at the file-offset level so that decoding
    a chunk from the middle of a file still produces the right result.

    Args:
        data:        Bytes to decode (chunk from the file).
        key:         The 8-byte XOR key from xor.dat.
        file_offset: The byte offset in the file where `data` starts.
                     This ensures the key rolls correctly even when
                     reading the file in chunks.

    Returns:
        Decoded bytes of the same length as `data`.

    Example:
        key = load_xor_key("fixtures/xor.dat")
        raw_chunk = f.read(1024)
        decoded = xor_decode(raw_chunk, key, file_offset=0)
    """
    if is_null_key(key):
        # Key is all zeros: XOR with 0 is identity — no decoding needed.
        return data

    key_len = len(key)
    return bytes(
        b ^ key[(file_offset + i) % key_len]
        for i, b in enumerate(data)
    )
