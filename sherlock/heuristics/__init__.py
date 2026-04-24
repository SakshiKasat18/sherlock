"""
Sherlock heuristics package.

Each heuristic module exposes a single class inheriting HeuristicBase
with an `analyze(tx) -> dict` method.

The engine.py module collects all heuristics and runs them over each tx.
"""
from .engine import HeuristicEngine, HEURISTICS, run_heuristics, classify_transaction
