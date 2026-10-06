# Thamani — Agentic AI Value-for-Money Analyst for Kenyan Public Tenders

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-brightgreen.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-orange.svg)](https://github.com/jlowin/fastmcp)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-purple.svg)](https://github.com/langchain-ai/langgraph)

---

## 1. Overview & Mission
**Thamani** (Swahili for *value* or *worth*) is an agentic AI value-for-money analysis engine built for public procurement oversight in Kenya.

Public procurement represents a significant portion of government expenditure. However, tender officers, internal auditors, and oversight bodies often evaluate tender awards in isolation without instant empirical price benchmarks, supplier concentration histories, or structural entity resolution. 

Thamani autonomously ingests historical procurement data, benchmarks contract award values against 9 years of empirical category baselines, audits supplier win concentration across procuring entities, merges corporate legal entity spelling variants, and compiles an evidence-backed briefing with structural citations for human decision-makers.

---

## 2. Challenge Track & Theme
Built for the **African Agentic AI Design Challenge**:
- **Track**: Governance
- **Theme**: Financial Services / Value for Money
- **Submission Deadline**: 15 October 2026

Thamani addresses governance and financial stewardship by turning open procurement disclosures into proactive, automated audit intelligence.

---

## 3. Human-in-the-Loop Non-Negotiables
**The system prepares the briefing; it never awards, shortlists, or disqualifies.**

1. **No Autonomous Finalization**: No code path in Thamani can finalize or archive an output without a named human officer's explicit approval (`approve` or `override`).
2. **Forbidden Recommendation Phrasing**: Award and outcome recommendation language (e.g., *"should award to X"*, *"winner"*, *"should select"*, *"recommend awarding"*) is structurally forbidden in both finding text and draft briefing generation.
3. **Audit Trail Invariance**: Every human interaction (officer name, timestamp, override explanation, or rejection) is permanently stamped onto the finalized report and execution run log.

---

## 4. End-to-End Analysis Workflow
Given an input Tender or Award OCID (e.g. `ocds-5whusi-PCKTTI-2695`):

1. **`plan`**: Deterministically organizes the 6-stage execution graph.
2. **`fetch`**: Retrieves tender metadata, buyer information, and award records from the local SQLite cache.
3. **`benchmark`**: Evaluates contract award amount against category baselines (works / goods / services) for median, P25, P75, and P99 metrics, and pulls the 5 nearest historical contracts as empirical citations.
4. **`supplier_check`**: Groups historical awards by normalized supplier name (`norm_name()`), counts historical wins, tracks distinct buyer entities, flags buyer concentration (≥8 wins with 1 buyer), and notes merged alias spellings.
5. **`draft`**: Enforces strict structural citation validation. Every finding must cite one or more valid OCIDs, or the draft is structurally rejected.
6. **`gate`**: Halts for human review via the CLI. The officer reads the briefing and submits `approve`, `override <finding-id> <note>`, or `reject`.
7. **`finalize`**: Appends the officer's verification record and writes the locked briefing to disk via the borrowed Filesystem MCP server.

---

## 5. System Architecture
Thamani combines open-source orchestration with fast embedded data querying and the Model Context Protocol:

- **Orchestration**: Built on **LangGraph** (pure open-source state graph; zero closed no-code builders).
- **Tool Protocol**: **FastMCP** (Model Context Protocol standard) exposing reusable analysis tools.
- **Embedded Database**: Local SQLite database with Write-Ahead Logging (WAL) and category-indexed caching.
- **Execution Log**: Append-only telemetry written to `runs/<utc-timestamp>.jsonl`.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for full architectural schematics and component interaction flowcharts.

---

## 6. Open Data Contract (Kenya PPRA OCDS)
Thamani operates purely on official, open procurement disclosure datasets provided by the **Public Procurement Regulatory Authority (PPRA)** through the Public Procurement Information Portal (PPIP) and the **Open Contracting Partnership (OCP) Data Registry (Publication 147)**.

- **Temporal Coverage**: 2018 to 2026 (9 years of procurement history).
- **Dataset Scale**: **260,744 tenders** and **113,246 awards** (matching verified data contract).
- **Currency Homogeneity**: 100% of native historical awards are in Kenya Shillings (`KES`).
- **Category Baselines**:
  - **Works**: Median ~2,500,658 KES | P99 ~263,343,153 KES (n=36,796)
  - **Goods**: Median ~291,140 KES | P99 ~51,334,592 KES (n=50,267)
  - **Services**: Median ~303,600 KES | P99 ~156,000,000 KES (n=24,845)
- **Privacy & Compliance**: Company entities only. No personal data, and no live unawarded tenders in progress.

---

## 7. MCP Tool Suite (Custom + Borrowed)

### Custom Analysis Tools (`thamani-server`, FastMCP)
1. **`ocds_fetch(ocid: str) -> dict`**: Queries tender and award metadata from the local database, attaching document provenance.
2. **`price_benchmark(category: str, value_amount: float, currency: str) -> dict`**: Calculates statistical percentiles, triggers outlier/watch verdicts, flags non-positive or absurd values (>1000× median), and identifies the 5 nearest comparator awards.
3. **`briefing_draft(findings: list[dict], ...) -> dict`**: Validates mandatory source citations and produces the 5-section Markdown briefing.

### Borrowed Community Tool (`filesystem` MCP)
- **Tool**: Standard Filesystem MCP Server Adapter (`FilesystemMCPClient`).
- **Application Justification**: *Rebuilding file I/O adds nothing; our engineering goes into the analysis tools.* Wired exclusively to the `finalize` stage to persist approved briefings to `reports/`.

---

## 8. Quickstart & Installation

### Prerequisites
- Python 3.12+
- Git

### Installation
```bash
# 1. Clone repository
git clone https://github.com/Atwoto/thamani.git
cd thamani

# 2. Install dependencies
pip install -r requirements.txt
```

---

## 9. Database Ingestion & Rebuild
Rebuild the local SQLite cache anytime using the verified OCDS ingestion script:

```bash
python -m src.thamani_server.ocds --years 2018 2019 2020 2021 2022 2023 2024 2025 2026 --db data/thamani.sqlite --data-dir data
```

Downloads compressed `.jsonl.gz` releases directly from the OCP Registry and populates indexed SQLite tables in under 3 minutes.

---

## 10. CLI Usage & Flags
All workflows are accessible through `python -m src.agent.loop`:

### Run a Single Award
```bash
python -m src.agent.loop --award ocds-5whusi-1033 --officer "Jane Doe, CPO"
```

### Run the Deterministic 3-Case Demo
```bash
python -m src.agent.loop --demo
```

### Single Category Price Benchmark
```bash
python -m src.agent.loop --benchmark --category works --value 500000000
```

### Run Evaluation Suite (3× Majority Verdicts)
```bash
python -m src.agent.loop --eval
```

---

## 11. Evaluation Results Summary
The test harness runs all 9 specification tasks **3× each**:

| Task | Description | Status |
| :---: | :--- | :---: |
| 1 | Known price outlier (>P99) flagged with 5+ cited OCIDs | **PASS** |
| 2 | At-median award evaluates to `ok` with zero false flags | **PASS** |
| 3 | AMARK supplier concentration flagged with historical award IDs | **PASS** |
| 4 | Broken/missing supplier ID handled gracefully via alias normalization | **PASS** |
| 5 | Missing buyer name logs warning and completes without crashing | **PASS** |
| 6 | Absurd value (>1000× median) triggers `data-quality` flag, not price verdict | **PASS** |
| 7 | Officer override at gate permanently recorded in final report | **PASS** |
| 8 | Full 6-stage pipeline completes under open-weights / deterministic planner | **PASS** |
| 9 | Synthetic mixed-currency case (Foreign FX normalization) | **EXPECTED FAIL** |

See [`EVALS.md`](EVALS.md) for full run traces and the documented honest failure rationale for Task 9.

---

## 12. 3-Minute Demo Video Script & Walkthrough
The demo video follows this strict, unedited single-take script:

| Timing | Scene & Screen Action | Key Talking Points |
| :--- | :--- | :--- |
| **0:00 – 0:20** | Terminal launch: `python -m src.agent.loop --demo` | Introduce Thamani as an agentic AI value-for-money analyst for Kenyan public procurement. |
| **0:20 – 1:20** | Tool calls visible on screen: `ocds_fetch → price_benchmark → supplier_check → briefing_draft` | Point out the 6-step LangGraph flow, FastMCP tool execution, and empirical price benchmarking against 9 years of real PPRA data. |
| **1:20 – 2:00** | Live findings on screen | Highlight Case 1 (AMARK concentration: 200 wins from 1 buyer) and Case 2 (African Touch Safaris: 10 spelling variants merged into 1 entity). |
| **2:00 – 2:30** | Human gate CLI interaction | Officer types override with justification. Show Case 3 (zero-value contract flagged honestly as data quality anomaly, not false price verdict). |
| **2:30 – 2:50** | Final briefing report inspection | Show finalized report in `reports/` with complete OCID source citations and signed Officer Gate Verification Record. |
| **2:50 – 3:00** | Wrap-up | Conclude within 3 minutes; emphasize open-source orchestration, strict governance, and human-in-the-loop compliance. |

---

## 13. License & Governance
- **License**: MIT License. See [`LICENSE`](LICENSE).
- **Ethical Boundary**: Open data only (Kenya OCDS/PPRA). No classified, personal, or live tenders evaluated.
- **Challenge Compliance**: Fully compliant with African Agentic AI Design Challenge rules.
