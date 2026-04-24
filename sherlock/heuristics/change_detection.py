"""
change_detection.py — Change Output Detection Heuristic.

In a Bitcoin payment, typically one output is the payment (to the recipient)
and one is the "change" returned to the sender. Identifying the change output
reveals the payment amount and links the input wallet to the change output.

Detection methods (applied in priority order):
    1. script_type_match   — change output has same script type as inputs
    2. round_number        — non-round outputs are more likely change
    3. position_heuristic  — last output is often change (wallet convention)

Rules applied:
    - Skip coinbase (no real payment vs change)
    - Skip OP_RETURN outputs (not real outputs)
    - Need >= 2 real outputs to detect change vs payment
    - UTXO consolidation (1 output) has no change

Confidence model:
    "high"   → script_type_match with all inputs agreeing on one type
    "medium" → script_type_match with mixed input types, or round_number
    "low"    → position_heuristic only

Known limitations:
    - CoinJoin transactions confuse this (many equal outputs)
    - P2SH wraps many script types — harder to match
    - Taproot/P2TR universal adoption reduces effectiveness over time
"""

from collections import Counter

from .base import HeuristicBase
from ..parser.transaction_model import ParsedTransaction

# Script types excluded from "real output" counting
_NON_PAYMENT_TYPES = frozenset({"op_return"})

# Round satoshi thresholds (10k sat up to 10 BTC)
_ROUND_AMOUNTS = frozenset({
    10_000,          # 0.0001 BTC
    100_000,         # 0.001 BTC
    1_000_000,       # 0.01 BTC
    10_000_000,      # 0.1 BTC
    100_000_000,     # 1 BTC
    1_000_000_000,   # 10 BTC
})


class ChangeDetectionHeuristic(HeuristicBase):
    ID = "change_detection"
    NAME = "Change Detection"

    def analyze(self, tx: ParsedTransaction) -> dict:
        if tx.is_coinbase:
            return self._not_detected()

        real_outputs = [o for o in tx.outputs if o.script_type not in _NON_PAYMENT_TYPES]
        if len(real_outputs) < 2:
            return self._not_detected()

        # Method 1: Script type match
        result = self._script_type_match(tx, real_outputs)
        if result:
            return result

        # Method 2: Round number payment
        result = self._round_number(tx, real_outputs)
        if result:
            return result

        # Method 3: Position heuristic (last output = change)
        return self._position_heuristic(real_outputs)

    def _script_type_match(self, tx: ParsedTransaction, real_outputs: list) -> dict | None:
        """
        The change output's script type typically matches the dominant input script type.
        The payment goes to the recipient's (possibly different) address type.
        """
        # Collect input script types (only resolved inputs)
        input_types = [
            inp.script_type for inp in tx.inputs
            if inp.script_type and inp.script_type not in _NON_PAYMENT_TYPES
        ]
        if not input_types:
            return None

        type_counts = Counter(input_types)
        dominant_type, dominant_count = type_counts.most_common(1)[0]

        # Find outputs matching the dominant input type
        matching = [o for o in real_outputs if o.script_type == dominant_type]
        non_matching = [o for o in real_outputs if o.script_type != dominant_type]

        if len(matching) == 1 and len(non_matching) >= 1:
            # Exactly one output matches input script type → likely change
            change_out = matching[0]
            all_same_type = dominant_count == len(input_types)
            confidence = "high" if all_same_type else "medium"
            return {
                "detected": True,
                "likely_change_index": change_out.index,
                "method": "script_type_match",
                "confidence": confidence,
            }

        return None

    def _round_number(self, tx: ParsedTransaction, real_outputs: list) -> dict | None:
        """
        Payments tend to be round BTC amounts; change is whatever is left
        (thus a non-round amount). If exactly one output is non-round, it's likely change.
        """
        round_outs = [o for o in real_outputs if o.value in _ROUND_AMOUNTS]
        non_round_outs = [o for o in real_outputs if o.value not in _ROUND_AMOUNTS]

        if len(round_outs) >= 1 and len(non_round_outs) == 1:
            change_out = non_round_outs[0]
            return {
                "detected": True,
                "likely_change_index": change_out.index,
                "method": "round_number",
                "confidence": "medium",
            }
        return None

    def _position_heuristic(self, real_outputs: list) -> dict:
        """
        Wallets often place change as the last output.
        Low-confidence fallback when other methods fail.
        """
        change_out = real_outputs[-1]
        return {
            "detected": True,
            "likely_change_index": change_out.index,
            "method": "position_heuristic",
            "confidence": "low",
        }
