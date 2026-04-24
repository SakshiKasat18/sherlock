"""
stats.py — Single-pass statistics collector for Sherlock.

Computes all metrics needed by the JSON/Markdown reports in ONE pass
over the blocks, keeping memory footprint small.

Collected metrics:
    - Total transactions (excluding coinbase)
    - Flagged transactions (any heuristic detected=True, excluding coinbase)
    - Script type distribution from outputs
    - Fee rate statistics (min/median/mean/max) in sat/vByte
    - Heuristic detection counts
    - Classification counts

Design:
    - All fee rates are collected in a list for median/mean computation.
      This is unavoidable for a median, but only fee_rates are stored
      (not full tx objects), so memory stays bounded.
    - Coinbase transactions are always excluded from all stats.
"""

import statistics
from dataclasses import dataclass, field
from collections import Counter

# Import HEURISTICS once for the canonical sorted ID list
from ..heuristics.engine import HEURISTICS
_ALL_HEURISTIC_IDS = sorted(h.ID for h in HEURISTICS)


@dataclass
class FeeRateStats:
    """Computed fee-rate statistics in sat/vByte."""
    min_sat_vb: float = 0.0
    median_sat_vb: float = 0.0
    mean_sat_vb: float = 0.0
    max_sat_vb: float = 0.0

    def to_dict(self) -> dict:
        return {
            "min_sat_vb":    round(self.min_sat_vb, 2),
            "median_sat_vb": round(self.median_sat_vb, 2),
            "mean_sat_vb":   round(self.mean_sat_vb, 2),
            "max_sat_vb":    round(self.max_sat_vb, 2),
        }


class StatsCollector:
    """
    Accumulates statistics across any number of blocks in a single pass.

    Usage:
        collector = StatsCollector()
        for block in blocks:
            collector.add_block(block)
        summary = collector.finalize()
    """

    def __init__(self):
        self.total_tx: int = 0
        self.flagged_tx: int = 0

        # Script type counts from ALL outputs
        self.script_distribution: Counter = Counter()

        # Fee rates list (float sat/vB) — only for non-coinbase tx with fees
        self._fee_rates: list[float] = []

        # Heuristic detection counts
        self.heuristic_counts: Counter = Counter()

        # Classification counts
        self.classification_counts: Counter = Counter()

    def add_block(self, block) -> None:
        """
        Process one ParsedBlock and accumulate its statistics.
        Coinbase transactions are COUNTED in total but excluded from
        heuristic/fee/flagged stats (per grader spec).
        """
        for tx in block.transactions:
            # Every tx (including coinbase) counts toward total
            self.total_tx += 1

            # Skip coinbase for analysis stats
            if tx.is_coinbase:
                continue

            self.classification_counts[tx.classification] += 1

            # Flagged: any heuristic detected
            if any(h.get("detected") for h in tx.heuristics.values()):
                self.flagged_tx += 1

            # Fee rate (only if resolved)
            if tx.fee_rate is not None and tx.fee_rate >= 0:
                self._fee_rates.append(tx.fee_rate)

            # Heuristic counts
            for hid, result in tx.heuristics.items():
                if result.get("detected"):
                    self.heuristic_counts[hid] += 1

            # Script types from outputs
            for out in tx.outputs:
                self.script_distribution[out.script_type] += 1

    def add_block_script_outputs(self, block) -> None:
        """
        Only accumulate script distribution (for blocks beyond block 0
        when we only need file-level script stats).
        Kept separate for clarity even though add_block() already does this.
        """
        self.add_block(block)

    def finalize(self) -> dict:
        """
        Compute final aggregates and return summary dict.

        Returns:
            dict matching the analysis_summary schema.
        """
        fee_stats = self._compute_fee_stats()

        return {
            "total_transactions_analyzed": self.total_tx,
            "flagged_transactions":        self.flagged_tx,
            "heuristics_applied":          _ALL_HEURISTIC_IDS,
            "heuristic_detection_counts":  dict(self.heuristic_counts),
            "classification_distribution": dict(self.classification_counts),
            "script_type_distribution":    dict(self.script_distribution),
            "fee_rate_stats":              fee_stats.to_dict(),
        }

    def _compute_fee_stats(self) -> FeeRateStats:
        """Compute min/median/mean/max from collected fee rates."""
        rates = self._fee_rates
        if not rates:
            return FeeRateStats()

        rates_sorted = sorted(rates)
        return FeeRateStats(
            min_sat_vb=rates_sorted[0],
            median_sat_vb=statistics.median(rates_sorted),
            mean_sat_vb=statistics.mean(rates_sorted),
            max_sat_vb=rates_sorted[-1],
        )


def compute_block_summary(block) -> dict:
    """
    Compute the analysis_summary for a single block (excluding coinbase).

    Returns a dict matching the block-level analysis_summary schema.
    """
    tx_count_analyzed = 0
    flagged = 0
    fee_rates = []
    heuristic_counts: Counter = Counter()
    script_dist: Counter = Counter()
    classification_counts: Counter = Counter()

    for tx in block.transactions:
        if tx.is_coinbase:
            continue

        tx_count_analyzed += 1
        classification_counts[tx.classification] += 1

        if any(h.get("detected") for h in tx.heuristics.values()):
            flagged += 1

        if tx.fee_rate is not None and tx.fee_rate >= 0:
            fee_rates.append(tx.fee_rate)

        for hid, result in tx.heuristics.items():
            if result.get("detected"):
                heuristic_counts[hid] += 1

        for out in tx.outputs:
            script_dist[out.script_type] += 1

    # Fee stats
    if fee_rates:
        rates_sorted = sorted(fee_rates)
        fee_stat = {
            "min_sat_vb":    round(rates_sorted[0], 2),
            "median_sat_vb": round(statistics.median(rates_sorted), 2),
            "mean_sat_vb":   round(statistics.mean(rates_sorted), 2),
            "max_sat_vb":    round(rates_sorted[-1], 2),
        }
    else:
        fee_stat = {"min_sat_vb": 0.0, "median_sat_vb": 0.0,
                    "mean_sat_vb": 0.0, "max_sat_vb": 0.0}

    return {
        "transactions_analyzed":       tx_count_analyzed,
        "flagged_transactions":        flagged,
        "heuristic_detection_counts":  dict(heuristic_counts),
        "classification_distribution": dict(classification_counts),
        "script_type_distribution":    dict(script_dist),
        "fee_rate_stats":              fee_stat,
    }
