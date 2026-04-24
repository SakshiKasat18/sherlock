"""
coinjoin.py — CoinJoin Detection Heuristic.

CoinJoin is a privacy technique where multiple users combine their inputs
into a single transaction with equal-value outputs, making it hard to trace
which input funded which output.

Detection criteria:
    - >= 3 inputs (multiple participants)
    - >= 2 non-OP_RETURN outputs share the *exact* same value

This is a strong signal because legitimate payments rarely produce
many equal-value outputs by coincidence.

Confidence:
    >= 5 equal-value outputs → "high"
    >= 3 equal-value outputs → "medium"
    2 equal-value outputs    → "low"

Known limitations:
    - Batch payments (e.g., exchange withdrawals) can trigger false positives
      if they happen to use the same withdrawal amount
    - CoinJoins with unequal output sizes (Taproot CoinJoins) won't be detected
    - Empty-transaction sweeps with equal dust outputs may trigger this

Reference:
    Maxwell, G. (2013). CoinJoin: Bitcoin privacy for the real world.
    BitcoinTalk.
"""

from collections import Counter

from .base import HeuristicBase
from ..parser.transaction_model import ParsedTransaction

_NON_PAYMENT_TYPES = frozenset({"op_return"})


class CoinJoinHeuristic(HeuristicBase):
    ID = "coinjoin"
    NAME = "CoinJoin Detection"

    def analyze(self, tx: ParsedTransaction) -> dict:
        if tx.is_coinbase:
            return self._not_detected()

        if len(tx.inputs) < 3:
            return self._not_detected()

        real_outputs = [o for o in tx.outputs if o.script_type not in _NON_PAYMENT_TYPES]
        if len(real_outputs) < 2:
            return self._not_detected()

        # Count output values — look for shared exact values
        value_counts = Counter(o.value for o in real_outputs)
        max_equal = value_counts.most_common(1)[0][1]  # highest duplicate count

        if max_equal < 2:
            return self._not_detected()

        # Confidence based on how many outputs share the dominant equal value
        if max_equal >= 5:
            confidence = "high"
        elif max_equal >= 3:
            confidence = "medium"
        else:
            confidence = "low"

        # The equal value that appears most
        equal_value = value_counts.most_common(1)[0][0]

        return {
            "detected": True,
            "confidence": confidence,
            "equal_output_count": max_equal,
            "equal_output_value": equal_value,
            "input_count": len(tx.inputs),
        }
