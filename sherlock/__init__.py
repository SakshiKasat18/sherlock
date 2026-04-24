"""
Sherlock — Bitcoin Chain Analysis Engine

Processes raw Bitcoin block data (blk*.dat / rev*.dat) and applies
behavioral heuristics to extract patterns, classify transactions,
and produce structured JSON and Markdown reports.

Pipeline:
    raw blocks → parser → prevout resolution → heuristic engine
    → classification → JSON/MD reports

Public entry point:
    from sherlock.analysis.analyzer import analyze
"""

__version__ = "1.0.0"
