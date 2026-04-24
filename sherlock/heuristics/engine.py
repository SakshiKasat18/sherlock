"""
engine.py — Heuristic engine for Sherlock.

Loads all heuristics from the registry and runs them over each transaction.
Also provides the transaction classifier (priority-based classification).

Usage:

    from sherlock.heuristics import run_heuristics, classify_transaction

    # Run all heuristics, returns dict {heuristic_id: result_dict}
    results = run_heuristics(tx)

    # Classify based on heuristic results
    label = classify_transaction(results)

    # Or both in one step via HeuristicEngine:
    engine = HeuristicEngine()
    results = engine.analyze(tx)   # stored in tx.heuristics, tx.classification

Transaction Classification Priority (high → low):
    coinjoin         — privacy tx, highest specificity
    consolidation    — UTXO cleanup
    batch_payment    — exchange/payroll pattern
    self_transfer    — address reuse detected, all change
    simple_payment   — 1-2 outputs (most common case)
    unknown          — fallback
"""

from ..parser.transaction_model import ParsedTransaction
from .base import HeuristicBase
from .cioh import CIOHHeuristic
from .change_detection import ChangeDetectionHeuristic
from .coinjoin import CoinJoinHeuristic
from .consolidation import ConsolidationHeuristic
from .address_reuse import AddressReuseHeuristic
from .round_number_payment import RoundNumberHeuristic
from .batch_payment import BatchPaymentHeuristic


# ── Heuristic registry — add new heuristics here ────────────────────────────
HEURISTICS: list[HeuristicBase] = [
    CIOHHeuristic(),
    ChangeDetectionHeuristic(),
    CoinJoinHeuristic(),
    ConsolidationHeuristic(),
    AddressReuseHeuristic(),
    RoundNumberHeuristic(),
    BatchPaymentHeuristic(),
]


def run_heuristics(tx: ParsedTransaction) -> dict:
    """
    Run all registered heuristics on a single transaction.

    All heuristic IDs are ALWAYS present in the returned dict, even if
    not detected (value: {"detected": False}).  This makes the JSON
    schema uniform across all transactions.

    Args:
        tx: A ParsedTransaction (prevouts resolved for best results).

    Returns:
        dict mapping heuristic_id → result_dict.
        Example:
            {
                "cioh":              {"detected": True, "confidence": "high", ...},
                "change_detection":  {"detected": True, "likely_change_index": 1, ...},
                "coinjoin":          {"detected": False},
                ...
            }
    """
    # Pre-populate with not-detected so all keys are always present
    results: dict[str, dict] = {h.ID: {"detected": False} for h in HEURISTICS}
    for heuristic in HEURISTICS:
        try:
            results[heuristic.ID] = heuristic.analyze(tx)
        except Exception:
            results[heuristic.ID] = {"detected": False}
    return results


def classify_transaction(heuristic_results: dict) -> str:
    """
    Classify a transaction based on heuristic detection results.

    Priority (highest specificity first):
        1. coinjoin      — strong signal takes precedence
        2. consolidation — UTXO cleanup
        3. batch_payment — multi-recipient payment
        4. self_transfer — address reuse, change only (no payment)
        5. simple_payment — 1-2 real outputs
        6. unknown        — fallback

    Args:
        heuristic_results: Returned by run_heuristics().

    Returns:
        str: Classification label.
    """
    def detected(key: str) -> bool:
        return heuristic_results.get(key, {}).get("detected", False)

    if detected("coinjoin"):
        return "coinjoin"

    if detected("consolidation"):
        return "consolidation"

    if detected("batch_payment"):
        return "batch_payment"

    # Self-transfer: address reuse AND no payment going out
    # (change detection fired, indicating the tx may be sending back to self)
    if detected("address_reuse") and detected("change_detection"):
        # Only if no non-matching output (i.e. could be pure self-transfer)
        # Keep it simple: label as self_transfer if both fire together
        return "self_transfer"

    # Simple payment: CIOH or change detection fired but nothing specific
    # Most normal transactions fall here
    if detected("cioh") or detected("change_detection"):
        return "simple_payment"

    return "unknown"


class HeuristicEngine:
    """
    Orchestrates heuristic analysis for an entire block.

    run_block(block) runs all heuristics on every transaction in the block
    and stores results directly in tx.heuristics and tx.classification.
    """

    def __init__(self, heuristics: list[HeuristicBase] | None = None):
        """
        Args:
            heuristics: Optional custom heuristic list. Defaults to HEURISTICS.
        """
        self.heuristics = heuristics or HEURISTICS

    def analyze(self, tx: ParsedTransaction) -> dict:
        """
        Run all heuristics on tx, store results in tx.heuristics and
        tx.classification, and return the result dict.
        """
        results: dict[str, dict] = {}
        for heuristic in self.heuristics:
            try:
                results[heuristic.ID] = heuristic.analyze(tx)
            except Exception:
                results[heuristic.ID] = {"detected": False}

        tx.heuristics = results
        tx.classification = classify_transaction(results)
        return results

    def run_block(self, block) -> None:
        """
        Run heuristics on every transaction in a block (in-place update).

        Args:
            block: ParsedBlock — modified in place.
        """
        for tx in block.transactions:
            self.analyze(tx)
