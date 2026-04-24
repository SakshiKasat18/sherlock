.PHONY: install test run analyze clean

# ── Variables ─────────────────────────────────────────────────────────────────
PYTHON   ?= python3
BLK      ?= fixtures/blk04330.dat
REV      ?= fixtures/rev04330.dat
XOR      ?= fixtures/xor.dat
PORT     ?= 3000

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	$(PYTHON) -m pip install -e ".[dev]"

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v --tb=short

test-cov:
	$(PYTHON) -m pytest tests/ -v --cov=sherlock --cov-report=term-missing

# ── Run analysis pipeline ─────────────────────────────────────────────────────
analyze:
	./cli.sh --block $(BLK) $(REV) $(XOR)

# ── Web dashboard ─────────────────────────────────────────────────────────────
run:
	PORT=$(PORT) ./web.sh

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/
