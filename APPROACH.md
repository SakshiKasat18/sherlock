# Approach

This document describes the methodology behind **Sherlock — Bitcoin Chain Analysis Engine**, a system that parses raw Bitcoin block data, reconstructs transaction flows, detects behavioral patterns using heuristics, and produces structured analytics outputs.

---

## 1. System Overview

Sherlock is a single-transaction chain analysis engine. It does not traverse the full blockchain graph. Instead, it extracts maximum information from each transaction in isolation by combining raw script byte analysis with resolved previous outputs (UTXOs) from Bitcoin Core's undo data files.

The main pipeline:

1. **Block parsing** — read and XOR-decode `blk*.dat` files from Bitcoin Core storage
2. **Prevout reconstruction** — parse `rev*.dat` undo data to resolve input values and script types
3. **Transaction analysis** — compute fees, fee rates, virtual sizes, and script type distributions
4. **Heuristic detection** — apply 7 behavioral heuristics to every non-coinbase transaction
5. **Statistical aggregation** — collect flagged counts, script distributions, fee statistics per block and per file
6. **Report generation** — emit a machine-readable JSON report and a human-readable Markdown report

All components are written in pure Python using only the standard library.

---

## 2. Parsing Architecture

Raw Bitcoin blocks are stored as contiguous binary records in `blk*.dat` files, XOR-encoded with an 8-byte key stored in `xor.dat`. The parser:

1. **XOR-decodes** each byte in the file using the rotating 8-byte key from `xor.dat`
2. **Detects magic bytes** (`0xD9B4BEF9` for mainnet) to locate block record boundaries
3. **Parses the 80-byte block header**: version, previous block hash, merkle root, time, bits, nonce
4. **Computes the block hash**: double-SHA256 of the header bytes, reversed for display (little-endian convention)
5. **Iterates transactions**: reads each transaction using CompactSize-encoded field counts

For each transaction, the parser extracts:

- **Inputs**: `prev_txid`, `prev_vout`, `scriptSig`, `sequence`, and SegWit `witness` data
- **Outputs**: `value` (satoshis), `scriptPubKey` bytes, and derived `script_type`
- **Metadata**: `txid` (double-SHA256 of non-witness serialization), `wtxid`, `vsize`, `is_coinbase` flag

Script type classification (`p2pkh`, `p2wpkh`, `p2sh`, `p2wsh`, `p2tr`, `op_return`, `unknown`) is performed by pattern-matching the raw `scriptPubKey` bytes — no address derivation or external libraries are used.

Integer values throughout the system are stored in satoshis to avoid floating-point arithmetic.

---

## 3. Prevout Reconstruction

Bitcoin Core writes undo (reverse) data alongside block data so that blocks can be disconnected during reorgs. Each record in `rev*.dat` corresponds to one block and stores the previous outputs spent by that block's transactions. Sherlock exploits this data to reconstruct full input information.

The undo data is structured as:

- `CBlockUndo`: one record per block, containing one `CTxUndo` per non-coinbase transaction
- `CTxUndo`: one `CTxInUndo` per input, each containing the spent `TxOut` (value + scriptPubKey)
- Values are stored using Bitcoin Core's compact amount encoding (`CompressedAmount`)
- Scripts are stored using Bitcoin Core's compressed script encoding (`CompressedScript`)

After matching undo records to parsed inputs, each input gains:

- **`value`**: satoshi amount of the spent UTXO
- **`script_pubkey`**: raw bytes of the spent output's scriptPubKey
- **`script_type`**: derived type string of the input's spending script

This enables:
- **Fee calculation**: `fee = sum(input_values) - sum(output_values)` for non-coinbase transactions
- **Fee rate**: `fee_rate = fee / vsize` in sat/vByte
- **Input script type analysis**: used by Change Detection and CIOH heuristics

---

## 4. Heuristic Detection Engine

Heuristics are applied to every non-coinbase transaction via a **plugin registry**. Each heuristic is an independent module implementing `analyze(tx) -> dict` and returning a result dict with at minimum `{"detected": bool}`. All 7 heuristic IDs are always present in `tx.heuristics`, even when not detected.

Classification priority (highest to lowest): `coinjoin` → `consolidation` → `batch_payment` → `self_transfer` → `simple_payment` → `unknown`.

---

### Common Input Ownership (CIOH)

**What it detects:** Transactions where multiple distinct inputs are assumed to belong to the same wallet. The CIOH assumption states that if a transaction has multiple inputs, all inputs were signed by the same entity.

**Detection logic:** Triggered when `input_count >= 2` and the transaction is not already classified as CoinJoin (which deliberately breaks this assumption). Confidence scales with input count: `low` (2–3 inputs), `medium` (4–9 inputs), `high` (≥10 inputs).

**Confidence model:** Higher input counts increase the probability that a single wallet is consolidating UTXOs or paying from a unified balance, making attribution more reliable.

**Limitations:** CoinJoin transactions intentionally pool inputs from different wallets. PayJoin (P2EP) transactions also break this assumption. CIOH produces false positives for CoinJoin participants if the CoinJoin heuristic does not fire first.

---

### Change Detection

**What it detects:** In a typical Bitcoin payment, one output is the payment and a second output returns change to the sender. Change Detection identifies which output is most likely the change output.

**Detection logic (three methods in priority order):**
1. **Script type match**: If exactly one output has the same script type as the majority of inputs, that output is likely change (medium confidence).
2. **Round number payment**: If one output has a round satoshi value and another does not, the non-round output is the change (high confidence if difference is large).
3. **Position heuristic**: Change outputs often appear last. If there are exactly 2 non-OP_RETURN outputs, the last one is flagged as probable change (low confidence).

OP_RETURN outputs are excluded from all change detection analysis.

**Confidence model:** Method 1 = medium, Method 2 = high, Method 3 = low. Detection stops at the first method that finds a candidate.

**Limitations:** Wallets that always use P2TR or script re-randomization confuse the script-type method. Merchants who accept exact amounts defeat round-number detection.

---

### CoinJoin Detection

**What it detects:** CoinJoin transactions, where multiple parties combine inputs into a single transaction to obscure which inputs fund which outputs. The canonical signature is multiple equal-value outputs.

**Detection logic:** Requires `input_count >= 2` and at least 2 non-OP_RETURN outputs sharing the same satoshi value. Confidence scales with the number of equal-value outputs: `low` (2–3 equal outputs), `medium` (4–6), `high` (≥7).

**Confidence model:** More participants (equal outputs) means stronger evidence of deliberate coordination, increasing confidence that this is privacy mixing rather than a coincidence.

**Limitations:** A merchant sending identical invoices to multiple customers could accidentally match the pattern. Small-participant CoinJoins (2 equal outputs) are easily confused with normal payments.

---

### Consolidation Detection

**What it detects:** Transactions that consolidate many small UTXOs into one or a few outputs — a common wallet hygiene operation performed during low-fee periods.

**Detection logic:** Triggered when `input_count >= 3` and `non_op_return_output_count <= 2`. The input-to-output ratio determines confidence: `low` (3–5 inputs), `medium` (6–9 inputs), `high` (≥10 inputs).

**Confidence model:** Higher ratios (many inputs, few outputs) indicate deliberate UTXO consolidation rather than normal payment behavior.

**Limitations:** Some exchange withdrawal transactions have similar structure. A transaction with 3 inputs sending to 2 recipients (one payment + one change) may be misclassified.

---

### Address Reuse

**What it detects:** Transactions where the same scriptPubKey appears in both the inputs (being spent) and the outputs (receiving funds). This is a privacy anti-pattern because it links different UTXO sets to the same entity.

**Detection logic:** Computes the intersection of `{input.script_pubkey for input in tx.inputs if input.script_pubkey}` and `{output.script_pubkey for output in tx.outputs}`. If the intersection is non-empty, address reuse is detected. Confidence is always `high` because this is a deterministic check with no ambiguity.

**Confidence model:** Always `high` — if the same scriptPubKey appears in inputs and outputs, it is definitively address reuse.

**Limitations:** Some wallet implementations deliberately send change back to the same address (self-transfer pattern). This heuristic does not distinguish intentional from accidental reuse.

---

### Round Number Payments

**What it detects:** Transactions where at least one output value is a round number (divisible by a large power of 10), which strongly suggests a human-specified payment amount.

**Detection logic:** For each non-OP_RETURN output, checks divisibility thresholds in descending order: 10M sat (0.1 BTC), 1M sat, 100k sat, 10k sat, 1k sat, 100 sat. If any output matches a threshold, the transaction is flagged. Confidence is `high` for ≥1M sat rounding, `medium` otherwise.

**Confidence model:** Larger round amounts are set by humans more deliberately, making `high` confidence appropriate. Smaller round values (100 sat) are more likely coincidental.

**Limitations:** Automated payment systems can produce round amounts programmatically. Satoshi-precise exchange rates occasionally produce round output values by chance.

---

### Batch Payment

**What it detects:** Transactions from a single sender to many recipients — typical of exchange withdrawals, payroll systems, or mixing services distributing funds.

**Detection logic:** Triggered when `input_count <= 3` (few sources indicate single sender) and `non_op_return_output_count >= 5` (many distinct recipients). Confidence scales with output count: `low` (5–9 outputs), `medium` (10–19 outputs), `high` (≥20 outputs).

**Confidence model:** More outputs with few inputs more strongly imply a coordinated single-sender batch operation.

**Limitations:** Consolidation + payment in a single transaction can look like a batch. CoinJoin transactions can also match this pattern if the CoinJoin heuristic does not fire first.

---

## 5. Confidence Model

Every heuristic result contains at minimum:

```json
{"detected": true, "confidence": "high"}
```

Confidence levels follow a three-tier model:

| Level  | Meaning |
|--------|---------|
| `high` | Pattern strongly matches the expected behavior with low probability of coincidence |
| `medium` | Pattern matches but alternative explanations exist |
| `low` | Weak signal; pattern is consistent with the heuristic but easily confused with normal behavior |

Confidence values represent **relative evidence strength**, not probability percentages. They are used to prioritize suspicious transactions in the dashboard and spotlight sections of the report, not to make definitive attributions.

---

## 6. Statistical Aggregation

Statistics are computed in a single streaming pass over all blocks to minimize memory usage. Only fee rates are collected in a list (required for median computation); all other statistics are accumulated in `Counter` objects.

**File-level aggregates** (across all blocks):
- `total_transactions_analyzed`: all transactions including coinbase
- `flagged_transactions`: non-coinbase transactions where any heuristic detected
- `heuristics_applied`: sorted list of all 7 heuristic IDs
- `script_type_distribution`: output script type counts from non-coinbase transactions
- `classification_distribution`: transaction classification label counts
- `fee_rate_stats`: computed from `fee / vsize` for each non-coinbase transaction with resolved prevouts

Fee rate formula:
```
fee_rate (sat/vByte) = transaction_fee / virtual_size
```

Where `virtual_size = ceil((non_witness_size * 4 + witness_size) / 4)`.

Coinbase transactions are included in `total_transactions_analyzed` but excluded from all heuristic detection, classification, fee, and flagged counts — they have no inputs to analyze and pay no fees.

---

## 7. Architecture Overview

```
repo/
  sherlock/
    parser/
      xor.py              — XOR key loading and byte decoding
      block_file.py       — blk*.dat iteration
      block.py            — block header + transaction parsing
      script.py           — scriptPubKey type classification
      undo.py             — rev*.dat CTxInUndo / CBlockUndo parsing
      transaction_model.py — ParsedBlock, ParsedTransaction data classes
    utils/
      varint.py           — Bitcoin CompactSize / VarInt decoding
      hashing.py          — double-SHA256 utilities
      io.py               — binary stream helpers
    heuristics/
      base.py             — HeuristicBase abstract class
      cioh.py, change_detection.py, coinjoin.py,
      consolidation.py, address_reuse.py,
      round_number_payment.py, batch_payment.py
      engine.py           — run_heuristics(), classify_transaction()
    analysis/
      stats.py            — StatsCollector (single-pass aggregation)
      classifier.py       — classify_block()
      report_json.py      — out/<stem>.json writer
      report_md.py        — out/<stem>.md writer
      analyzer.py         — full pipeline entry point: analyze()
  web/
    server.py             — stdlib HTTP server (/api/health, /api/block/<stem>)
    static/               — dashboard HTML + CSS + JS (Chart.js)
  cli.sh                  — ./cli.sh --block <blk.dat> <rev.dat> <xor.dat>
  web.sh                  — ./web.sh  (starts server, prints URL)
```

---

## 8. Trade-offs and Design Decisions

- **Single-transaction scope**: All heuristics operate on individual transactions only. No blockchain-wide graph traversal. This sacrifices some precision (e.g., we cannot detect peeling chains across blocks) for guaranteed O(inputs + outputs) per transaction.
- **Satoshi integers everywhere**: Floating-point BTC values are never used internally. Fees, values, and thresholds are all integer satoshi amounts.
- **Script bytes over addresses**: scriptPubKey bytes are compared directly. Address derivation (base58check, bech32) adds complexity and failure modes for unknown script types.
- **Plugin heuristic registry**: Adding a new heuristic requires only creating a new file and adding one line to the registry in `engine.py`.
- **Memory efficiency**: The JSON report includes full transaction lists in every block (≈3.1 MB for 84 blocks / 341k transactions). For larger runs, a streaming JSON writer would be needed.

---

## 9. Limitations of Chain Analysis

Blockchain heuristics are **probabilistic**, not definitive. This system identifies patterns that are *consistent with* certain behaviors — it does not prove ownership or intent.

Known sources of inaccuracy:

- **CoinJoin and PayJoin**: Privacy-enhanced transactions deliberately break CIOH and change detection assumptions
- **Wallet software variations**: Different wallets place change at different output positions (first, last, random)
- **Batching**: Exchanges batch withdrawals in ways that superficially resemble consolidations
- **Address reuse policies**: Some protocols (e.g., certain Lightning channel operations) reuse addresses intentionally
- **Script type diversity**: Taproot (P2TR) internal-key spends look identical regardless of wallet software, limiting script-type-based change detection
- **Round amounts in automated systems**: Payment processors and exchange settlements can produce round values for non-human reasons

The outputs of this system should be treated as **investigative leads** rather than conclusions.

---

## References

- [Bitcoin Developer Guide — Transactions](https://developer.bitcoin.org/devguide/transactions.html)
- [BIP141 — Segregated Witness](https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki)
- [BIP341 — Taproot](https://github.com/bitcoin/bips/blob/master/bip-0341.mediawiki)
- [Bitcoin Core source: src/serialize.h, src/undo.h](https://github.com/bitcoin/bitcoin)
- [An Analysis of Anonymity in the Bitcoin System — Reid & Harrigan (2011)](https://arxiv.org/abs/1107.4524)
- [A Fistful of Bitcoins: Characterizing Payments Among Men with No Names — Meiklejohn et al. (2013)](https://dl.acm.org/doi/10.1145/2504730.2504747)
- [CoinJoin: Bitcoin Privacy for the Real World — Greg Maxwell (2013)](https://bitcointalk.org/index.php?topic=279249.0)
