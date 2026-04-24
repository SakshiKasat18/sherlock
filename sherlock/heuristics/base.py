"""
base.py — Abstract base class for all Sherlock heuristics.

All heuristics must inherit from HeuristicBase and implement `analyze()`.
This enforces a consistent interface that the engine can iterate over.
"""

from abc import ABC, abstractmethod

from ..parser.transaction_model import ParsedTransaction


class HeuristicBase(ABC):
    """
    Abstract base for all chain-analysis heuristics.

    Subclasses must define:
        ID   (str) — e.g. "cioh"
        NAME (str) — e.g. "Common Input Ownership"
        analyze(tx) -> dict

    The analyze() return value must contain at minimum:
        { "detected": bool }

    Optional keys: confidence, method, likely_change_index, details, ...
    """

    ID: str = ""
    NAME: str = ""

    @abstractmethod
    def analyze(self, tx: ParsedTransaction) -> dict:
        """
        Analyze one transaction and return a heuristic result dict.

        Args:
            tx: Fully parsed transaction (with prevouts resolved if Phase 4 ran).

        Returns:
            dict with at minimum {"detected": bool}.
            Additional fields are heuristic-specific.
        """
        ...

    # Convenience: always available, no analysis needed
    @staticmethod
    def _not_detected() -> dict:
        return {"detected": False}
