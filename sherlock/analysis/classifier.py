"""
classifier.py — Transaction behavior classifier.

This module re-exports the classify_transaction function from the heuristic
engine, and also provides block-level classification utilities.

Classification priority (highest specificity first):

    coinjoin         CoinJoin privacy mix (equal outputs, many inputs)
    consolidation    UTXO cleanup (many inputs → very few outputs)
    batch_payment    One sender → many recipients (exchange/payroll)
    self_transfer    All outputs return to sender (address reuse + change)
    simple_payment   Normal payment (1-2 outputs, change identified)
    unknown          No patterns matched

Classification is based solely on heuristic results for the single
transaction — no graph traversal, no blockchain lookups.

Usage:

    from sherlock.analysis.classifier import classify_transaction, classify_block

    label = classify_transaction(heuristic_results)
    classify_block(block)   # updates block.transactions[i].classification in-place
"""

from ..heuristics.engine import classify_transaction, HeuristicEngine


def classify_block(block, engine: HeuristicEngine | None = None) -> None:
    """
    Run heuristics and classify every transaction in a block.

    Modifies each ParsedTransaction in-place:
        tx.heuristics     = {heuristic_id: result_dict, ...}
        tx.classification = "coinjoin" | "consolidation" | ... | "unknown"

    Args:
        block:  ParsedBlock — modified in place.
        engine: Optional custom HeuristicEngine. Defaults to global registry.
    """
    _engine = engine or HeuristicEngine()
    _engine.run_block(block)


__all__ = ["classify_transaction", "classify_block"]
