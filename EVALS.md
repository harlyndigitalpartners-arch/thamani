# Thamani - Evaluation Suite & Benchmark Results

This evaluation suite tracks and proves the reliability, guardrails, and structural citation enforcement of Thamani across 9 verified tasks.

All tasks are executed **3× each** to verify deterministic convergence under the pinned Kenya OCDS SQLite database (`data/thamani.sqlite`).

## 1. Summary Results Table

| Task # | Evaluation Task Description | Iteration 1 | Iteration 2 | Iteration 3 | Majority Verdict | Target Expected | Status |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | Known price outlier → flagged with cited OCIDs | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified |
| **2** | At-median award → no flags | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified |
| **3** | AMARK-style concentration → flagged with award IDs | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified |
| **4** | Broken supplier-id scheme → handled, run continues | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified |
| **5** | Missing buyer name → logged warning, no crash | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified |
| **6** | Absurd value (>1000× norm) → data-quality verdict | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified |
| **7** | Officer override at gate → logged with id/ts/note in final | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified |
| **8** | NVIDIA Nemotron call → computed draft → pending human gate | PASS | PASS | PASS | **PASS** | PASS | ✅ Verified 2026-10-08 |
| **9** | Synthetic mixed-currency case → EXPECTED FAIL | FAIL | FAIL | FAIL | **FAIL** | FAIL | ⚠️ Expected Fail |

**Total Result**: 8 passing evaluation tasks and 1 documented expected failure. The expected failure remains unresolved.

---

## 2. Detailed Task Breakdown

### Task 1: Known Price Outlier (High Works Award)
- **Input**: Category: `works`, Award Value: `500,000,000 KES`
- **Baseline**: Works P99 is ~263.3M KES, 3× Median is ~7.5M KES
- **Behavior**: Flagged as price outlier (`flag`).
- **Citation Check**: Returns 5 closest historical benchmark awards (`ocds-5whusi-KCG/PSM/1491258/2023/2024`, `ocds-5whusi-CGK/SCM/TCT/0T/001/2022-2023`, etc.).

### Task 2: At-Median Award
- **Input**: Category: `works`, Award Value: `2,500,000 KES`
- **Baseline**: Works Median is ~2,500,658 KES
- **Behavior**: Evaluated as `ok`. No outlier flags generated.

### Task 3: Supplier Concentration (AMARK Northern Agency)
- **Input**: Tender OCID `ocds-5whusi-PCKTTI-2695`
- **Database Reality**: Duplicate-aware analysis counts 195 distinct recorded awards across 9 years, all from `PC KINYANJUI TECHNICAL TRAINING INSTITUTE`. The earlier 200 figure counted duplicated stored rows.
- **Behavior**: Generates `concentration` finding with `HIGH` severity. Citations explicitly reference past award OCIDs.

### Task 4: Broken Supplier-ID Scheme
- **Input**: Award record with missing/corrupted `supplier_id`.
- **Behavior**: Pipeline normalizes name using corporate entity stripper (`norm_name()`), logs data quality note, and successfully proceeds through drafting and gate.

### Task 5: Missing Buyer Name
- **Input**: OCID `ocds-5whusi-275077-PBSS/2025/2026/001`
- **Behavior**: Missing procuring entity logs a warning, falls back to safe metadata placeholder, registers a data quality finding, and completes drafting without crashing.

### Task 6: Absurd Value Anomaly (>1000× Category Median)
- **Input**: Award Value: `3,750,000,000 KES` (3.75B KES, >1,500× works median)
- **Behavior**: Rather than giving an unrealistic statistical comparison or recommendation, the engine classifies the record as a `data-quality` anomaly.

### Task 7: Officer Override at Human Gate
- **Input**: CLI gate command `override finding-1 <note>` with named officer.
- **Behavior**: Execution waits strictly for human input; overrides are formally stamped with officer identity, timestamp, and audit trail in the finalized report.

### Task 8: NVIDIA Open-Weight Model Execution
- **Input**: `ocds-5whusi-1033`, model `nvidia/nemotron-3.5-lightning-30b-a3b`, three live calls using the NVIDIA API.
- **Behavior**: Traverses `plan → fetch → benchmark → supplier_check → model focus → draft → gate → finalize`. All three calls returned valid existing finding IDs. The gate remained `pending`, so no report was finalized by this evaluation. Execution logs were persisted to `runs/*.jsonl`.

---

## 3. Task 9: Documented Honest Failure Note (Mixed-Currency FX Normalization)

### Background & Failure Definition
In Kenyan public procurement (PPRA/PPIP), 99.9% of historical award records are denominated in Kenya Shillings (KES). When a foreign or synthetic currency (e.g., `USD`, `EUR`, `GBP`) is presented for comparative price benchmarking:
- An apples-to-apples percentile and median comparison against KES historical baselines is invalid without accurate, point-in-time foreign exchange (FX) conversion.
- The system currently refuses to guess or apply static exchange rates, safely routing the record to a `data-quality` verdict path with note: `"currency USD not comparable to KES history"`.

### What Was Tried
1. **Static FX Multipliers**: Rejected because historical contracts span from 2018 to 2026, during which USD/KES shifted from ~100 to ~160 and back to ~128. Static multipliers introduce false inflation anomalies.
2. **Dynamic In-Prompt Currency Conversion**: LLM FX conversion hallucinated exchange rates across historical dates and violated our non-negotiable rule that benchmarks must be computed, never generated.

### Planned Next Steps (Roadmap)
1. **Currency Code Inference**: Validate currency codes against ISO 4217.
2. **Historical Central Bank of Kenya (CBK) FX Join**: Ingest official daily CBK exchange rates into a local SQLite table (`fx_rates(date, currency, rate_to_kes)`).
3. **Point-in-Time Purchasing Power Normalization**: Convert contract value using the rate published on the contract's specific `award_date`.
4. **Low-Confidence Manual-Review Flag**: When FX conversions are applied, flag the resulting benchmark with a low-confidence badge requiring mandatory officer review.


## Reliability regression verification ? 2026-10-13

`python -m pytest -q`: **33 passed** (96.94 seconds).

Checks cover re-ingestion and legacy duplicate migration, database changes and separation, joint-supplier award counting, KES filtering, non-finite values, complete verification-record checksums, HTML escaping, officer and override validation, report version preservation, logs surviving failed writes, interactive demo gates, the three real-data pipelines stopping at pending review, Streamlit approve/reject flows, and a real stdio round trip to the community filesystem MCP server.

The snapshot contains 109,237 distinct award identities within 113,246 stored rows. Duplicate-aware analysis gives AMARK 195 distinct awards; earlier 200-win summaries counted stored rows. Category benchmarks remain screening comparisons without scope, quantity, year or inflation controls. Version 2 checksums are integrity checks, not authenticated signatures or immutable archives.

Live NVIDIA calls were not repeated in this verification. The historical Task 8 results above remain historical evidence, and current model tests use mocked responses. FX conversion remains outside scope.

## Submission verification — 2026-10-14

`python -m pytest -q`: **35 passed** (47.73 seconds). The installed community filesystem MCP server was exercised through a real stdio round trip. Live NVIDIA calls were not repeated; the historical live model results above remain separate evidence.
