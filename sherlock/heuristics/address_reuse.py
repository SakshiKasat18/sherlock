"""
address_reuse.py — Address Reuse Detection Heuristic.

Address reuse occurs when the same scriptPubKey appears in both the
inputs and outputs of a transaction, or when a scriptPubKey that was
previously spent is used again as an output.

Within a transaction, reuse links the input owner to the output —
privacy-degrading because it confirms the same entity controls both.

Detection: compare the set of input scriptPubKeys vs output scriptPubKeys.
If any overlap exists → detected.

Note: We compare raw bytes of scriptPubKey, not derived addresses.
This avoids ambiguity in address encoding and covers all script types.

Confidence:
    Any reuse detected → "high" (deterministic, not probabilistic)

Known limitations:
    - OP_RETURN outputs are excluded (unspendable, no reuse possible)
    - CoinJoin transactions may artificially trigger this
    - Change being sent back to sender is the most common cause
      (and expected behavior for many wallets)

Reference:
    Androulaki, E. et al. (2013). Evaluating user privacy in Bitcoin.
    Financial Cryptography and Data Security.
"""

from .base import HeuristicBase
from ..parser.transaction_model import ParsedTransaction

_NON_PAYMENT_TYPES = frozenset({"op_return"})


class AddressReuseHeuristic(HeuristicBase):
    ID = "address_reuse"
    NAME = "Address Reuse"

    def analyze(self, tx: ParsedTransaction) -> dict:
        if tx.is_coinbase:
            return self._not_detected()

        # Build set of input scriptPubKeys (only resolved ones)
        input_scripts = {
            inp.script_pubkey
            for inp in tx.inputs
            if inp.script_pubkey is not None
        }

        if not input_scripts:
            return self._not_detected()

        # Build set of output scriptPubKeys (exclude unspendable OP_RETURN)
        output_scripts = {
            out.script_pubkey
            for out in tx.outputs
            if out.script_type not in _NON_PAYMENT_TYPES
        }

        # Check for any overlap
        reused = input_scripts & output_scripts   # set intersection — O(min(|A|, |B|))

        if not reused:
            return self._not_detected()

        return {
            "detected": True,
            "confidence": "high",
            "reuse_count": len(reused),
        }
