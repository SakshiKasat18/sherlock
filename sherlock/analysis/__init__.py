"""
Sherlock analysis package.

Contains higher-level analysis utilities:
    stats.py       — statistics aggregation (single-pass)
    classifier.py  — transaction classifier
    report_json.py — JSON report generator
    report_md.py   — Markdown report generator
    analyzer.py    — main pipeline runner
"""
from .analyzer import analyze
from .classifier import classify_transaction, classify_block
from .stats import StatsCollector, compute_block_summary
