"""
cioh.py — Common Input Ownership Heuristic (CIOH).

CIOH is the foundational chain-analysis assumption:
    If a transaction has multiple inputs, all inputs likely belong
    to the same entity (wallet), because only that entity could sign
    all of them simultaneously.

Detection criteria:
    len(inputs) >= 2 → detected

Confidence:
    >= 5 inputs → "high"
    2-4 inputs  → "medium"
    1 input     → not detected (always single-signer)

Known limitations:
    - False positives in CoinJoin transactions (multiple owners, one tx)
    - MultiSig UTXOs where multiple parties must sign together
    - Does not apply to coinbase transactions (no real inputs)

Reference:
    Nakamoto, S. (2008). Bitcoin: A Peer-to-Peer Electronic Cash System.
    Section 10: Privacy.
"""

from .base import HeuristicBase
from ..parser.transaction_model import ParsedTransaction


class CIOHHeuristic(HeuristicBase):
    ID = "cioh"
    NAME = "Common Input Ownership"

    def analyze(self, tx: ParsedTransaction) -> dict:
        # Skip coinbase — no real inputs
        if tx.is_coinbase:
            return self._not_detected()

        n = len(tx.inputs)

        if n < 2:
            return self._not_detected()

        confidence = "high" if n >= 5 else "medium"

        return {
            "detected": True,
            "confidence": confidence,
            "input_count": n,
        }
