"""
consolidation.py — UTXO Consolidation Detection Heuristic.

Consolidation transactions combine many small UTXOs into fewer outputs.
Wallets do this to reduce UTXO fragmentation and future fee pressure.

Detection criteria:
    - >= 4 inputs (spending multiple UTXOs)
    - <= 2 non-OP_RETURN outputs

This is the opposite of CoinJoin — instead of many outputs, there are few.

Confidence:
    >= 10 inputs and 1 output → "high"
    >= 10 inputs and 2 outputs → "medium"
    4-9 inputs and <= 2 outputs → "low"

Known limitations:
    - Mining pool payouts (many inputs, 1 output) look like consolidations
    - Batched sweeps from exchanges can look similar
    - Cannot distinguish from deliberate large-input payments

Reference:
    Conti, M. et al. (2018). A Survey on Security and Privacy Issues of Bitcoin.
    IEEE Communications Surveys & Tutorials.
"""

from .base import HeuristicBase
from ..parser.transaction_model import ParsedTransaction

_NON_PAYMENT_TYPES = frozenset({"op_return"})


class ConsolidationHeuristic(HeuristicBase):
    ID = "consolidation"
    NAME = "Consolidation Detection"

    def analyze(self, tx: ParsedTransaction) -> dict:
        if tx.is_coinbase:
            return self._not_detected()

        n_inputs = len(tx.inputs)
        if n_inputs < 4:
            return self._not_detected()

        real_outputs = [o for o in tx.outputs if o.script_type not in _NON_PAYMENT_TYPES]
        n_real_outputs = len(real_outputs)

        if n_real_outputs > 2:
            return self._not_detected()

        # Confidence levels
        if n_inputs >= 10 and n_real_outputs == 1:
            confidence = "high"
        elif n_inputs >= 10 and n_real_outputs <= 2:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "detected": True,
            "confidence": confidence,
            "input_count": n_inputs,
            "output_count": n_real_outputs,
        }
