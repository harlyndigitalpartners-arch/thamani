# Thamani — End-to-End Build Specification

*For the coding agent. Read this file first, then build strictly in the order given in §10. Do not invent new tools, new data sources, or new deliverables. Scope discipline wins.*

## 0. Mission
Build Thamani, an agentic AI value-for-money analyst for Kenyan public tenders — African Agentic AI Design Challenge, Governance track, Financial services / Value for money theme.
Submission deadline: 15 October 2026.

**Non-negotiable rule**: the agent prepares the briefing file; it never awards, shortlists, or disqualifies. No code path may finalize output without a named human's explicit approval. Award/recommendation language (e.g. "should award to X") is forbidden anywhere in output.

## 1. The Loop (what the system does end to end)
Input: an award OCID (a tender OCID that has awards also works).
1. `ocds_fetch` pulls the award, its tender, supplier and buyer records from the local SQLite cache.
2. `price_benchmark` compares the award value against historical awards in the same `mainProcurementCategory` (works / goods / services): median, p99, outlier verdict.
3. `supplier_check` counts the supplier's past wins (on the normalized name) and distinct buyers; flags concentration and merges name variants.
4. `briefing_draft` assembles a markdown briefing. **Every finding must carry source citations (OCIDs) or validation rejects the draft.**
5. **Human gate (CLI)**: the named officer reads the draft and types `approve`, `override <finding-id> <note>`, or `reject`. The decision, identity and timestamp are appended to the run log. The loop waits — there is no timeout auto-approval.
6. **Finalize**: only reachable after approve/override. The final briefing is written to disk via the borrowed filesystem MCP server, with the gate record attached.

## 2. Repo Layout
Repo root: `thamani/`. Status of each file:
- `src/thamani_server/ocds.py` — Registry download + SQLite cache.
  Rebuild the database any time with:
  `python3 -m src.thamani_server.ocds --years 2018 2019 2020 2021 2022 2023 2024 2025 2026 --db data/thamani.sqlite --data-dir data`
- `src/thamani_server/server.py` — Implement the 3 FastMCP tools here (see §4).
- `src/agent/loop.py` — LangGraph planner-executor + CLI (see §6, §7).
- `data/thamani.sqlite` — build artifact, gitignored. Never commit data files.
- `data/*.jsonl.gz` — build artifact, gitignored.
- `README.md`, `ARCHITECTURE.md`, `EVALS.md`, `LICENSE`, `BUILD_SPEC.md` — docs; keep them true.

## 3. Data Contract (verified 2026-10-06 — do not re-derive, build on this)
SQLite tables (created by `ocds.py`):
- `tenders(ocid PK, tender_id, title, procurement_method, category, buyer_id, buyer_name, record_date)`
- `awards(id, ocid, award_id, award_date, value_amount REAL, value_currency, supplier_id, supplier_name, supplier_name_norm, buyer_id, buyer_name)`

Facts the design depends on:
- Tenders carry NO values and NO line items. Never benchmark a tender price; benchmark award values grouped by category. The agent's input is the award record.
- Dataset: 260,744 tenders, 109,237 awards (2018–2026). All values KES — no mixed currency exists in 9 years of real data.
- Category baselines (KES):
  - works → median 2,500,032 (n=35,581)
  - goods → 285,000 (n=48,099)
  - services → 299,310 (n=24,319)
  - p99: works 270.6M; goods 51.0M; services 155.7M
- 1,153 zero-value awards exist → these get a data-quality flag, never a price verdict.
- Buyer/supplier ids have no identifier scheme; names may have trailing spaces and case variants → always join/match suppliers on `supplier_name_norm` (see `norm_name()` in `ocds.py`).
- Known live cases for demo/evals:
  - `AMARK NORTHERN AGENCY LIMITED` — 188 wins from 1 buyer;
  - `AFRICAN TOUCH SAFARIS` / `AFRICAN TOUCH SAFARIS LIMITED` — same supplier, two spellings.

## 4. Tool Specifications (own MCP server: thamani-server, FastMCP)
### 4.1 `ocds_fetch(ocid: str) -> dict`
- Look up the OCID in SQLite. Raise a clear, catchable error if unknown (the agent retries with a corrected OCID; it must not hallucinate records).
- Return: tender title / method / category / buyer; the list of awards with value, currency, date, supplier name (+ normalized), buyer name; and every record's OCID as its source ref.
- Acceptance: `ocds_fetch` on the AMARK award OCID returns 188-win supplier history downstream.

### 4.2 `price_benchmark(category: str, value_amount: float, currency: str = "KES") -> dict`
- Query all valued awards in category from SQLite.
- Compute: n, median, p25, p75, p99.
- Verdict rules:
  - `value_amount <= 0` or missing → `{"verdict": "data-quality", "note": "non-positive award value"}`.
  - `currency != "KES"` → `{"verdict": "data-quality", "note": "currency <X> not comparable to KES history"}`.
  - `value > p99` or `value > 3 * median` → `"flag"`.
  - `value > 1.5 * median` → `"watch"`.
  - `else` → `"ok"`.
- Always return the cited stats (n, median, p99) **plus the OCIDs of the 5 nearest-value awards** as evidence. A verdict without cited OCIDs is a bug.
- Acceptance: a works award of KES 500M → flag; KES 2.5M works award → ok.

### 4.3 `briefing_draft(findings: list[dict]) -> dict`
- Each finding: `{id, kind, severity, text, sources}` where `kind ∈ price-outlier | concentration | data-quality`, `severity ∈ high | medium | low`, and `sources` is a non-empty list of OCIDs.
- Validation gate: if any finding lacks sources or text, return `{"valid": false, "errors": [...]}` and refuse to draft. This is what makes "every finding cites its document" structural, not a prompt wish.
- Output: markdown briefing with sections — Award summary · Price analysis · Supplier history · Data-quality notes · Officer decision (left blank for the gate).
- Forbidden strings in output: "award", "winner", "should select", "recommend awarding". The document describes and flags; it never recommends an outcome.

## 5. Borrowed MCP Server
The community `filesystem` MCP server handles report read/write. One-line justification (required on the application form): rebuilding file I/O adds nothing; our engineering goes into the analysis tools. Wire it as a second MCP client connection in the agent; use it only in the finalize node.

## 6. Agent Loop (LangGraph, open source — no closed no-code builders)
Graph nodes: `plan → fetch → benchmark → supplier_check → draft → gate → finalize`.
- State: `{ocid, tender, awards, benchmarks, findings, draft, gate_decision, run_log[]}`.
- `plan`: the LLM turns the input OCID into a step list. Keep it to a fixed 6-step template (the nodes above) — planning here means ordering and parameter-filling, not free-form.
- Every node appends `{ts, node, inputs_summary, outputs_summary}` to `run_log`. The full log persists to `runs/<utc-timestamp>.jsonl` (gitignored).
- `supplier_check` (plain Python node, no LLM needed): group awards by `supplier_name_norm`, count wins + distinct buyers per supplier; flag concentration when one supplier has ≥8 wins from a single buyer; merge name variants via `norm_name()` and note the merge.
- `gate`: print the draft to the terminal; prompt `approve | override <finding-id> <note> | reject`. Loop until one is entered. Record `{officer_name, decision, note, ts}` — officer name from `--officer` CLI flag (default `"Procurement Officer"`).
- `finalize`: unreachable unless `gate_decision ∈ {approve, override}`. Writes the final briefing (draft + gate record appended) via the filesystem MCP server.
- Model: NVIDIA-hosted open-weight Nemotron via `--model nvidia/nemotron-3.5-lightning-30b-a3b`. The model selects an existing finding for officer review; benchmarks, supplier checks, finding text, and citations are computed or retrieved, never generated. API credentials come from `NVIDIA_API_KEY` or `NVIDIA_API_KEY_FILE`.

## 7. CLI (`python -m src.agent.loop`)
- `--award <OCID>` — full end-to-end run on one award.
- `--demo` — runs the fixed demo scenario (AMARK concentration case + AFRICAN TOUCH variant-merge case + one zero-value data-quality case). This exact scenario is the <3 min demo video. It must be deterministic given the pinned database.
- `--eval` — executes EVALS.md tasks 1–9 (each 3×, majority verdict) and prints the pass/fail table. Task 9 is expected to FAIL (see §8).
- `--benchmark --category <works|goods|services> --value <amount>` — single benchmark call.
- `--officer "<name>"` — name recorded at the gate (default "Procurement Officer").

## 8. Evaluations
EVALS.md tasks 1–9:
1. Known price outlier → flagged with cited OCIDs.
2. At-median award → no flags.
3. AMARK-style concentration → flagged with award IDs.
4. Broken supplier-id scheme → handled, run continues.
5. Missing buyer name → logged warning, no crash.
6. Absurd value (1000× norm) → data-quality, not a price verdict.
7. Officer override at gate → logged with identity/ts/note; final reflects the human.
8. Full run with NVIDIA Nemotron → completes fetch → benchmark → model focus → draft → pending human gate.
9. Synthetic mixed-currency case → EXPECTED FAIL. Implement the data-quality verdict path (§4.2) but do not build FX normalization. Document in EVALS.md what was tried and what is next (currency inference → historical FX join → low-confidence manual-review flag).

Run-to-run variation: run each task 3×; the planner template is fixed so findings are deterministic given the pinned database snapshot (data/thamani.sqlite built 2026-10-06).

## 9. Demo Video Script (<3 min, single unedited take)
1. (0:00–0:20) Terminal: `pip install -r requirements.txt && python -m src.agent.loop --demo`.
2. (0:20–1:20) Tool calls visible on screen: `ocds_fetch → price_benchmark → supplier_check → briefing_draft`. Narrate one line each.
3. (1:20–2:00) The AMARK concentration flag and the AFRICAN TOUCH variant merge on screen.
4. (2:00–2:30) The human gate: officer overrides one finding with a note; the log updates. Include the zero-value award → data-quality flag as the honest-failure beat.
5. (2:30–2:50) The final briefing file, sources cited, gate record attached.
6. No slides, no cuts, tool calls visible throughout. Under 3 minutes.

## 10. Build Order (follow strictly)
1. `server.py`: implement `ocds_fetch` against the SQLite cache. Test standalone via MCP inspector.
2. `server.py`: implement `price_benchmark` (§4.2). Unit-test the verdict boundaries.
3. `loop.py`: LangGraph graph with stub LLM; wire the three tools; get `--benchmark` working.
4. `loop.py`: `supplier_check` node + `briefing_draft` validation gate (§4.3).
5. `loop.py`: human gate + finalize via borrowed filesystem server. Wire NVIDIA Nemotron; first full model-assisted review run.
6. `--eval` harness; run EVALS.md 3×; fill in real results; write the task-9 failure note honestly.
7. Record the demo video (§9). Verify README's 13 sections are all true. Finalize ARCHITECTURE.md.

## 11. Definition of Done
- [ ] Fresh clone → `pip install -r requirements.txt` → rebuild DB (one command, §2) → `python -m src.agent.loop --demo` completes with the gate.
- [ ] 3 own MCP tools callable; 1 borrowed server wired; every tool call logged.
- [x] Three NVIDIA Nemotron runs reached the pending human gate, with model calls recorded in `runs/`.
- [ ] EVALS.md filled with real results; exactly one documented unfixed failure.
- [ ] Demo video <3 min, unedited, tool calls on screen.
- [ ] Public repo, MIT licence, one-page ARCHITECTURE.md, honest README.
- [ ] Application form submitted with real links before 15 Oct 2026.

## 12. Constraints (from the challenge brief — violations disqualify)
- Own MCP server with 3+ tools, at least one that *does* something (ours: `price_benchmark`).
- One MCP server we did not write (`filesystem`), with the one-line justification (§5).
- Open-source orchestration only. AI coding assistance allowed — but the builder must be able to explain every line in the 10-minute live code walkthrough.
- Open data only (Kenya OCDS/PPRA). No live tenders in progress. No personal details — company records only.
- English submissions and output.
- New work built in the build window; existing open-source libraries are fine.
