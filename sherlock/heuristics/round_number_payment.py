"""
round_number_payment.py — Round Number Payment Detection Heuristic.

When users make payments, they often pay in round amounts (0.1 BTC,
0.01 BTC, 1 BTC, etc.). Non-round amounts (e.g. 0.03947621 BTC) are
more likely to be change outputs.

This heuristic flags transactions that contain at least one output
with a round satoshi value, suggesting a deliberate human-chosen amount.

Round value thresholds (in satoshis):
    10,000       = 0.0001 BTC (0.1 mBTC)
    100,000      = 0.001 BTC  (1 mBTC)
    1,000,000    = 0.01 BTC   (10 mBTC)
    10,000,000   = 0.1 BTC    (100 mBTC)
    100,000,000  = 1 BTC
    1,000,000,000 = 10 BTC

Design note:
    We check that at least ONE output is round; we don't require ALL.
    Even one round-value payment in a batch confirms the heuristic.

Confidence:
    Multiple round outputs → "high"
    Exactly one round output → "medium"

Known limitations:
    - Exchange withdrawals often use round amounts → false positives possible
    - Lightning channel opens frequently use 0.01 BTC → false positives
    - Miners may batch exact-amount payouts → false positives
"""

from .base import HeuristicBase
from ..parser.transaction_model import ParsedTransaction

_ROUND_AMOUNTS = frozenset({
    10_000,
    100_000,
    1_000_000,
    10_000_000,
    100_000_000,
    1_000_000_000,
})

_NON_PAYMENT_TYPES = frozenset({"op_return"})


class RoundNumberHeuristic(HeuristicBase):
    ID = "round_number_payment"
    NAME = "Round Number Payment"

    def analyze(self, tx: ParsedTransaction) -> dict:
        if tx.is_coinbase:
            return self._not_detected()

        # Collect round-value outputs (exclude OP_RETURN)
        round_outputs = [
            o for o in tx.outputs
            if o.script_type not in _NON_PAYMENT_TYPES
            and o.value in _ROUND_AMOUNTS
        ]

        if not round_outputs:
            return self._not_detected()

        confidence = "high" if len(round_outputs) >= 2 else "medium"

        return {
            "detected": True,
            "confidence": confidence,
            "round_output_count": len(round_outputs),
            "round_values": [o.value for o in round_outputs],
        }
