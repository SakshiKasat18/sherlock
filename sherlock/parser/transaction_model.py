"""
transaction_model.py — Immutable data model classes for parsed Bitcoin data.

These dataclasses are pure data containers — no parsing logic here.
Parsing logic lives in transaction_parser.py and block.py.

Separation of concerns:
    - Models define *what the data looks like* (fields, types, properties).
    - Parsers define *how to extract data from bytes*.

All heuristics, statistics, and report generators work with these models.

Design decisions:
    - Use @dataclass for clean field definitions and auto-__repr__.
    - Use field(default_factory=...) for mutable defaults.
    - fee and fee_rate are Optional because they require resolved prevouts
      (available only after Phase 4 rev.dat parsing).
    - heuristics and classification are populated by Phase 5/6 engine.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedInput:
    """
    One transaction input.

    A standard Bitcoin transaction input references a previous UTXO
    via (prev_txid, prev_vout). For coinbase transactions, prev_txid
    is 32 zero bytes and prev_vout is 0xFFFFFFFF.

    Witness data (SegWit) is stored separately in `witnesses`.
    Input values (from the spent UTXO) are resolved from rev.dat in Phase 4.
    """
    prev_txid: str          # hex64 — 0000...0000 for coinbase
    prev_vout: int          # 0xFFFFFFFF for coinbase
    script_sig: bytes       # scriptSig (empty for SegWit native inputs)
    sequence: int           # nSequence — RBF/timelock signaling

    # SegWit witness items — empty list for legacy inputs
    witnesses: list[bytes] = field(default_factory=list)

    # Resolved from rev.dat in Phase 4 (None until then)
    value: Optional[int] = None         # satoshis of the spent UTXO
    script_pubkey: Optional[bytes] = None   # scriptPubKey of the spent UTXO
    script_type: Optional[str] = None   # e.g. "p2wpkh", "p2pkh", etc.
    address: Optional[str] = None       # human-readable address (if derivable)

    @property
    def is_coinbase(self) -> bool:
        """Return True if this input is a coinbase (block reward) input."""
        return self.prev_txid == "0" * 64 and self.prev_vout == 0xFFFFFFFF


@dataclass
class ParsedOutput:
    """
    One transaction output — an unspent transaction output (UTXO).

    Contains the locking script (scriptPubKey) and the value in satoshis.
    Script type and address are decoded by the script classifier in Phase 3.
    """
    index: int              # 0-based position in outputs list
    value: int              # satoshis
    script_pubkey: bytes    # raw scriptPubKey bytes
    script_type: str        # "p2wpkh" | "p2pkh" | "p2sh" | "p2tr" |
                            # "p2wsh" | "op_return" | "p2pk" | "unknown"
    address: Optional[str] = None  # human-readable address (None for OP_RETURN)


@dataclass
class ParsedTransaction:
    """
    A fully parsed Bitcoin transaction.

    Contains all fields from the serialized transaction including
    SegWit witnesses. After Phase 4, fee and fee_rate are populated.
    After Phase 5/6, heuristics and classification are populated.
    """
    txid: str               # hex64 — computed from non-witness serialization
    version: int            # tx version (1 or 2)
    inputs: list[ParsedInput]
    outputs: list[ParsedOutput]
    locktime: int
    is_segwit: bool         # True if SegWit marker+flag were present
    size: int               # total serialized size in bytes (incl. witness)
    vsize: int              # virtual size = ceil(weight / 4)
    weight: int             # transaction weight for fee calculation

    # Populated in Phase 4 (rev.dat prevout resolution)
    fee: Optional[int] = None           # satoshis = sum(inputs) - sum(outputs)
    fee_rate: Optional[float] = None    # sat/vbyte = fee / vsize

    # Populated by Phase 5 heuristic engine
    heuristics: dict = field(default_factory=dict)  # heuristic_id → HeuristicResult

    # Populated by Phase 6 classifier
    classification: str = "unknown"

    @property
    def is_coinbase(self) -> bool:
        """Return True if this transaction is a coinbase (block reward) tx."""
        return (
            len(self.inputs) == 1
            and self.inputs[0].is_coinbase
        )

    @property
    def input_count(self) -> int:
        return len(self.inputs)

    @property
    def output_count(self) -> int:
        return len(self.outputs)

    @property
    def total_output_value(self) -> int:
        """Sum of all output values in satoshis."""
        return sum(o.value for o in self.outputs)


@dataclass
class ParsedBlock:
    """
    A fully parsed Bitcoin block containing its header and all transactions.

    Block hash is computed as double-SHA256(header_80_bytes) with bytes
    reversed (standard Bitcoin display convention).

    Block height is decoded from the coinbase scriptSig using BIP34
    (blocks >= 227,931 encode height as a script push in coinbase input).
    """
    # ── Header fields (from 80-byte block header) ─────────────────────────
    block_hash: str         # hex64 — double-SHA256 of header, byte-reversed
    version: int            # block version
    prev_block_hash: str    # hex64 of previous block
    merkle_root: str        # hex64 Merkle root of all transactions
    timestamp: int          # Unix timestamp
    bits: int               # compact difficulty target
    nonce: int              # proof-of-work nonce

    # ── Transactions ───────────────────────────────────────────────────────
    transactions: list[ParsedTransaction]

    # ── Decoded fields ─────────────────────────────────────────────────────
    block_height: int = 0   # decoded from coinbase BIP34 scriptSig

    @property
    def tx_count(self) -> int:
        return len(self.transactions)

    @property
    def coinbase_tx(self) -> Optional[ParsedTransaction]:
        """Return the first (coinbase) transaction, or None if empty."""
        return self.transactions[0] if self.transactions else None
