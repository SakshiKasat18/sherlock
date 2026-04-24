# Examples

Ready-to-run examples using the included fixture datasets.

## CLI — analyze a block file

```bash
# Analyze blk04330.dat (included fixture)
./examples/run_example.sh

# Analyze blk05051.dat
./examples/run_example.sh blk05051

# Or use make directly
make analyze BLK=fixtures/blk04330.dat

# With a custom block file
make analyze BLK=/path/to/blk00100.dat REV=/path/to/rev00100.dat
```

Output is written to `out/<stem>.json` and `out/<stem>.md`.

## Web UI — interactive analysis

```bash
make run
# Open http://127.0.0.1:3000
```

From the dashboard:
1. Select a dataset from the dropdown (precomputed results load instantly)
2. Click **Run Analysis** to re-run the pipeline on a fixture
3. Click **Upload .dat** to analyze any arbitrary block file

## Python API

```python
from pathlib import Path
from sherlock.analysis.analyzer import analyze

result = analyze(
    blk_path = Path("fixtures/blk04330.dat"),
    rev_path = Path("fixtures/rev04330.dat"),
    xor_path = Path("fixtures/xor.dat"),
    out_dir  = Path("out"),
    verbose  = True,
)

print(f"Analyzed {result['block_count']} blocks")
print(f"JSON report: {result['json_path']}")
print(f"Markdown report: {result['md_path']}")
```
