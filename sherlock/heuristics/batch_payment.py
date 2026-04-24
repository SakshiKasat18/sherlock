"""
batch_payment.py — Batch Payment Detection Heuristic.

Batch payments are transactions where a single sender pays multiple
recipients in one transaction. This is common for exchanges, payroll
systems, and payment processors, as it saves fees and blockchain space
compared to sending individual transactions.

Detection criteria:
    - <= 3 inputs (single or few UTXOs = single sender)
    - >= 5 non-OP_RETURN outputs (many recipients)

This profile is opposite to consolidation (many inputs, few outputs).

Confidence:
    >= 10 outputs and <= 2 inputs → "high"
    >= 7 outputs  and <= 3 inputs → "medium"
    >= 5 outputs  and <= 3 inputs → "low"

Known limitations:
    - CoinJoin transactions with few equal-value outputs could trigger this
    - High-volume exchange payouts overlap significantly with this pattern
    - The input count threshold is somewhat arbitrary (set at 3)

Reference:
    Möser, M. & Böhme, R. (2017). Anonymous Alone? Measuring Bitcoin's
    Second-Generation Anonymization Techniques. EuroS&P Workshops.
"""

from .base import HeuristicBase
from ..parser.transaction_model import ParsedTransaction

_NON_PAYMENT_TYPES = frozenset({"op_return"})


class BatchPaymentHeuristic(HeuristicBase):
    ID = "batch_payment"
    NAME = "Batch Payment"

    def analyze(self, tx: ParsedTransaction) -> dict:
        if tx.is_coinbase:
            return self._not_detected()

        n_inputs = len(tx.inputs)
        if n_inputs > 3:
            return self._not_detected()

        real_outputs = [o for o in tx.outputs if o.script_type not in _NON_PAYMENT_TYPES]
        n_real_outputs = len(real_outputs)

        if n_real_outputs < 5:
            return self._not_detected()

        # Confidence based on output count + input count
        if n_real_outputs >= 10 and n_inputs <= 2:
            confidence = "high"
        elif n_real_outputs >= 7:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "detected": True,
            "confidence": confidence,
            "input_count": n_inputs,
            "output_count": n_real_outputs,
        }
