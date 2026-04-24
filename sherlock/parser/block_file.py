"""
block_file.py — Iterate raw block payloads from a Bitcoin blk*.dat file.

A blk*.dat file is a sequence of records:

    [4 bytes] magic bytes  (network identifier, e.g. F9 BE B4 D9 for mainnet)
    [4 bytes] block size   (uint32 little-endian — size of the following block)
    [N bytes] block data   (raw block: 80-byte header + transactions)

A single blk*.dat file may contain many blocks — they are concatenated
one after another. The file is padded with null bytes at the end.

XOR Decoding:
    If a non-null xor.dat key is present, every byte of the file is
    XOR'd with key[file_offset % 8] before interpreting the data.
    We stream the file using mmap — no full load into RAM.

Note on file size:
    blk04330.dat is ~127 MB. We use mmap for efficient random access
    without loading the whole file into RAM at once.
"""

import mmap
import struct
from collections.abc import Iterator
from pathlib import Path

from .xor import xor_decode


# Bitcoin mainnet magic bytes (first 4 bytes of every block record)
MAINNET_MAGIC = b"\xf9\xbe\xb4\xd9"

# Size of the magic + block-size prefix preceding each block
RECORD_HEADER_SIZE = 8  # 4 magic + 4 size


def iter_blocks(path: str | Path, xor_key: bytes) -> Iterator[bytes]:
    """
    Yield raw block payloads from a Bitcoin blk*.dat file (XOR-decoded).

    Each yielded bytes object is the raw block payload ONLY:
      [80 bytes] block header
      [varint]   transaction count
      [...]      transactions

    Magic bytes and the size prefix are consumed but NOT yielded.

    Args:
        path:    Path to the blk*.dat file (str or Path).
        xor_key: 8-byte XOR key from xor.dat. Use bytes(8) for null key.

    Yields:
        bytes: Raw block payload for each block in the file.

    Example:
        key = load_xor_key(Path("fixtures/xor.dat"))
        for block_bytes in iter_blocks(Path("fixtures/blk04330.dat"), key):
            print("Block size:", len(block_bytes))
    """
    path = Path(path)

    with path.open("rb") as f:
        # mmap allows O(1) random access on a 127 MB file without
        # loading it entirely into RAM — ideal for large blk*.dat files.
        try:
            raw_map = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        except (mmap.error, ValueError):
            # Fallback for tiny/empty test files that mmap can't handle
            raw_map = f.read()

        file_size = len(raw_map)
        offset = 0

        while offset < file_size - RECORD_HEADER_SIZE:
            # ── Detect magic bytes (4 bytes) ─────────────────────────────────
            magic_raw = bytes(raw_map[offset: offset + 4])
            magic = xor_decode(magic_raw, xor_key, file_offset=offset)

            if magic != MAINNET_MAGIC:
                # Not a block boundary — skip one byte (handles null padding).
                offset += 1
                continue

            offset += 4  # Consumed: magic

            # ── Read block size (4 bytes, little-endian) ─────────────────────
            if offset + 4 > file_size:
                break

            size_raw = bytes(raw_map[offset: offset + 4])
            size_decoded = xor_decode(size_raw, xor_key, file_offset=offset)
            block_size = struct.unpack("<I", size_decoded)[0]
            offset += 4  # Consumed: size field

            # ── Sanity guards ────────────────────────────────────────────────
            if block_size == 0:
                continue  # Ghost record — skip

            if offset + block_size > file_size:
                break  # Truncated block at EOF — stop cleanly

            # ── Read and XOR-decode the block payload ─────────────────────────
            # file_offset is passed so XOR rolls correctly at the right position
            block_raw = bytes(raw_map[offset: offset + block_size])
            block_decoded = xor_decode(block_raw, xor_key, file_offset=offset)

            offset += block_size  # Advance past block

            # Yield ONLY the block payload — no magic, no size prefix
            yield block_decoded

        if isinstance(raw_map, mmap.mmap):
            raw_map.close()


def count_blocks(path: str | Path, xor_key: bytes) -> int:
    """
    Count total blocks in a blk*.dat file (iterates the full file).

    Args:
        path:    Path to the blk*.dat file.
        xor_key: 8-byte XOR key from xor.dat.

    Returns:
        int: Number of blocks found.
    """
    return sum(1 for _ in iter_blocks(path, xor_key))
