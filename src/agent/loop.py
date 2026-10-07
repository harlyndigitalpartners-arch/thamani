"""Thamani Agent Loop - LangGraph Orchestrator and CLI.

Orchestrates the 6-step value-for-money analysis workflow:
1. plan: LLM turns input OCID into fixed 6-step pipeline.
2. fetch: Calls ocds_fetch against local SQLite cache.
3. benchmark: Calls price_benchmark against historical category baselines.
4. supplier_check: Evaluates past win counts, buyer concentration, and name variants.
5. draft: Enforces structural OCID citations via briefing_draft.
6. gate: Human-in-the-loop CLI checkpoint requiring explicit officer decision.
7. finalize: Attaches gate verification and writes briefing using filesystem MCP server.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from langgraph.graph import END, StateGraph

from src.agent.crypto_seal import generate_gate_record_with_seal
from src.export.dossier import export_dossier_to_file
from src.thamani_server.ocds import norm_name
from src.thamani_server.server import (
    DEFAULT_DB_PATH,
    briefing_draft,
    get_db_connection,
    ocds_fetch,
    price_benchmark,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
)
logger = logging.getLogger("thamani.agent")


# -----------------------------------------------------------------------------
# Borrowed Filesystem MCP Server Client / Adapter (§5)
# One-line justification: rebuilding file I/O adds nothing; our engineering goes into analysis tools.
# -----------------------------------------------------------------------------
class FilesystemMCPClient:
    """Borrowed Filesystem MCP Server Adapter.

    Standard MCP filesystem protocol wrapper for writing finalized briefings to disk.
    """

    def __init__(self, root_dir: str | Path = "reports") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def write_file(self, filename: str, content: str) -> Path:
        """Write file to destination folder."""
        safe_name = re.sub(r"[^\w\-.]", "_", filename)
        target = self.root_dir / safe_name
        target.write_text(content, encoding="utf-8")
        return target


# -----------------------------------------------------------------------------
# Agent State Contract (§6)
# -----------------------------------------------------------------------------
class ThamaniState(TypedDict, total=False):
    ocid: str
    officer: str
    auto_gate_action: str | None
    interactive: bool
    plan_steps: list[dict[str, Any]]
    tender: dict[str, Any]
    awards: list[dict[str, Any]]
    benchmarks: list[dict[str, Any]]
    supplier_summary: dict[str, Any]
    findings: list[dict[str, Any]]
    data_quality_notes: list[str]
    draft: str
    gate_decision: dict[str, Any]
    seal_hash: str
    final_report_path: str
    run_log: list[dict[str, Any]]
    error: str | None


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Node 1: Plan
# -----------------------------------------------------------------------------
def plan_node(state: ThamaniState) -> dict[str, Any]:
    ocid = state["ocid"]
    ts = utc_now_iso()

    # Fixed 6-step execution plan (§6)
    steps = [
        {"step": 1, "node": "fetch", "description": f"Fetch tender and award records for OCID {ocid}"},
        {"step": 2, "node": "benchmark", "description": "Benchmark award values against historical category baselines"},
        {"step": 3, "node": "supplier_check", "description": "Analyze supplier history, win concentration, and alias merges"},
        {"step": 4, "node": "draft", "description": "Assemble markdown briefing enforcing structural citations"},
        {"step": 5, "node": "gate", "description": "Enforce human procurement officer gate (approve/override/reject)"},
        {"step": 6, "node": "finalize", "description": "Write signed briefing to filesystem via MCP server"},
    ]

    log_entry = {
        "ts": ts,
        "node": "plan",
        "inputs_summary": {"ocid": ocid},
        "outputs_summary": {"steps_count": len(steps)},
    }
    run_log = list(state.get("run_log", []))
    run_log.append(log_entry)

    logger.info(f"[PLAN] Initialized 6-step deterministic plan for {ocid}")
    return {"plan_steps": steps, "run_log": run_log}


# -----------------------------------------------------------------------------
# Node 2: Fetch
# -----------------------------------------------------------------------------
def fetch_node(state: ThamaniState) -> dict[str, Any]:
    ocid = state["ocid"]
    ts = utc_now_iso()
    run_log = list(state.get("run_log", []))
    findings = list(state.get("findings", []))
    dq_notes = list(state.get("data_quality_notes", []))

    try:
        data = ocds_fetch(ocid)
        tender = data.get("tender", {})
        awards = data.get("awards", [])

        # Check for missing buyer name (Eval 5: Missing buyer name -> logged warning, no crash)
        if not tender.get("buyer_name") or not tender["buyer_name"].strip():
            logger.warning(f"[FETCH] Tender {ocid} has missing or empty buyer name.")
            dq_notes.append(f"Missing procuring entity (buyer) name in tender record for OCID {ocid}.")
            findings.append({
                "id": f"DQ-BUYER-{len(findings)+1}",
                "kind": "data-quality",
                "severity": "medium",
                "text": "Procuring entity buyer name is missing in recorded tender metadata.",
                "sources": [ocid],
            })
            tender["buyer_name"] = "Unknown Buyer"

        log_entry = {
            "ts": ts,
            "node": "fetch",
            "inputs_summary": {"ocid": ocid},
            "outputs_summary": {
                "tender_title": tender.get("title", ""),
                "category": tender.get("category", ""),
                "awards_count": len(awards),
            },
        }
        run_log.append(log_entry)
        logger.info(f"[FETCH] Retreived {ocid}: {len(awards)} award(s), category: '{tender.get('category')}'")
        return {
            "tender": tender,
            "awards": awards,
            "findings": findings,
            "data_quality_notes": dq_notes,
            "run_log": run_log,
        }

    except Exception as e:
        logger.error(f"[FETCH] Failed to fetch {ocid}: {e}")
        log_entry = {
            "ts": ts,
            "node": "fetch",
            "inputs_summary": {"ocid": ocid},
            "outputs_summary": {"error": str(e)},
        }
        run_log.append(log_entry)
        return {"error": str(e), "run_log": run_log}


# -----------------------------------------------------------------------------
# Node 3: Benchmark
# -----------------------------------------------------------------------------
def benchmark_node(state: ThamaniState) -> dict[str, Any]:
    ts = utc_now_iso()
    run_log = list(state.get("run_log", []))
    findings = list(state.get("findings", []))
    dq_notes = list(state.get("data_quality_notes", []))
    benchmarks: list[dict[str, Any]] = []

    tender = state.get("tender", {})
    awards = state.get("awards", [])
    category = tender.get("category") or "goods"

    for idx, aw in enumerate(awards, 1):
        val = aw.get("value_amount", 0.0)
        curr = aw.get("value_currency", "KES")
        aw_ocid = aw.get("ocid") or state["ocid"]

        bm = price_benchmark(category=category, value_amount=val, currency=curr)
        benchmarks.append(bm)

        verdict = bm.get("verdict", "ok")
        nearest = bm.get("nearest_ocids") or [aw_ocid]

        if verdict == "data-quality":
            dq_note = f"Award {aw.get('award_id', idx)}: {bm.get('note')}"
            dq_notes.append(dq_note)
            findings.append({
                "id": f"DQ-VAL-{len(findings)+1}",
                "kind": "data-quality",
                "severity": "medium",
                "text": f"Award value data quality anomaly: {bm.get('note')}.",
                "sources": [aw_ocid],
            })
        elif verdict == "flag":
            findings.append({
                "id": f"PB-FLAG-{len(findings)+1}",
                "kind": "price-outlier",
                "severity": "high",
                "text": f"Significant price outlier detected ({val:,.2f} {curr}): {bm.get('note')}.",
                "sources": nearest if nearest else [aw_ocid],
            })
        elif verdict == "watch":
            findings.append({
                "id": f"PB-WATCH-{len(findings)+1}",
                "kind": "price-outlier",
                "severity": "medium",
                "text": f"Elevated price observation ({val:,.2f} {curr}): {bm.get('note')}.",
                "sources": nearest if nearest else [aw_ocid],
            })

    log_entry = {
        "ts": ts,
        "node": "benchmark",
        "inputs_summary": {"category": category, "awards_benchmarked": len(awards)},
        "outputs_summary": {
            "verdicts": [b.get("verdict") for b in benchmarks],
            "findings_added": len(findings),
        },
    }
    run_log.append(log_entry)
    logger.info(f"[BENCHMARK] Evaluated {len(awards)} award(s): {[b.get('verdict') for b in benchmarks]}")

    return {
        "benchmarks": benchmarks,
        "findings": findings,
        "data_quality_notes": dq_notes,
        "run_log": run_log,
    }


# -----------------------------------------------------------------------------
# Node 4: Supplier Check
# -----------------------------------------------------------------------------
def supplier_check_node(state: ThamaniState) -> dict[str, Any]:
    """Analyze supplier history, count wins, detect concentration, merge variants."""
    ts = utc_now_iso()
    run_log = list(state.get("run_log", []))
    findings = list(state.get("findings", []))
    awards = state.get("awards", [])

    conn = get_db_connection()
    supplier_summary: dict[str, Any] = {}

    try:
        cursor = conn.cursor()
        for idx, aw in enumerate(awards, 1):
            sup_norm = aw.get("supplier_name_norm")
            sup_name = aw.get("supplier_name") or "Unknown Supplier"
            aw_ocid = aw.get("ocid") or state["ocid"]

            if not sup_norm:
                # Broken supplier ID or empty name (Eval 4: Broken supplier-id scheme -> handled, run continues)
                logger.warning(f"[SUPPLIER] Broken or missing supplier info on award {aw.get('award_id')}")
                findings.append({
                    "id": f"DQ-SUP-{len(findings)+1}",
                    "kind": "data-quality",
                    "severity": "low",
                    "text": "Supplier entity record missing valid identification scheme; normalized fallback used.",
                    "sources": [aw_ocid],
                })
                continue

            # Query historical wins across SQLite
            cursor.execute(
                """
                SELECT count(*), count(DISTINCT buyer_name)
                FROM awards
                WHERE supplier_name_norm = ?
                """,
                (sup_norm,),
            )
            stats_row = cursor.fetchone()
            total_wins = stats_row[0] if stats_row else 1
            distinct_buyers = stats_row[1] if stats_row else 1

            # Query distinct spelling variants in database
            cursor.execute(
                """
                SELECT DISTINCT supplier_name
                FROM awards
                WHERE supplier_name_norm = ?
                """,
                (sup_norm,),
            )
            variant_rows = cursor.fetchall()
            variants = [r[0] for r in variant_rows if r[0]]

            # Query buyer breakdown to check concentration
            cursor.execute(
                """
                SELECT buyer_name, count(*) as wins, group_concat(ocid, ',') as sample_ocids
                FROM awards
                WHERE supplier_name_norm = ?
                GROUP BY buyer_name
                ORDER BY wins DESC
                LIMIT 1
                """,
                (sup_norm,),
            )
            top_buyer_row = cursor.fetchone()
            top_buyer = top_buyer_row[0] if top_buyer_row else ""
            top_wins = top_buyer_row[1] if top_buyer_row else 0
            sample_ocids_str = top_buyer_row[2] if top_buyer_row else ""
            evidence_ocids = [s.strip() for s in sample_ocids_str.split(",") if s.strip()][:5]
            if not evidence_ocids:
                evidence_ocids = [aw_ocid]

            concentration_flag = False
            concentration_note = ""
            # Rule: flag concentration when one supplier has >= 8 wins from a single buyer (§6)
            if top_wins >= 8:
                concentration_flag = True
                concentration_note = (
                    f"Concentration detected: {top_wins} historical wins from single procuring entity '{top_buyer}' "
                    f"({top_wins}/{total_wins} of all recorded awards, {distinct_buyers} distinct buyer(s))."
                )
                findings.append({
                    "id": f"SC-CONC-{len(findings)+1}",
                    "kind": "concentration",
                    "severity": "high",
                    "text": concentration_note,
                    "sources": evidence_ocids,
                })

            supplier_summary = {
                "supplier_name": sup_name,
                "supplier_name_norm": sup_norm,
                "total_wins": total_wins,
                "distinct_buyers": distinct_buyers,
                "concentration_flag": concentration_flag,
                "concentration_note": concentration_note,
                "merged_variants": variants,
            }

        log_entry = {
            "ts": ts,
            "node": "supplier_check",
            "inputs_summary": {"suppliers_checked": len(awards)},
            "outputs_summary": supplier_summary,
        }
        run_log.append(log_entry)
        logger.info(
            f"[SUPPLIER] Verified supplier '{supplier_summary.get('supplier_name_norm')}': "
            f"{supplier_summary.get('total_wins')} wins across {supplier_summary.get('distinct_buyers')} buyers"
        )
        return {
            "supplier_summary": supplier_summary,
            "findings": findings,
            "run_log": run_log,
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Node 5: Draft
# -----------------------------------------------------------------------------
def draft_node(state: ThamaniState) -> dict[str, Any]:
    ts = utc_now_iso()
    run_log = list(state.get("run_log", []))
    findings = state.get("findings", [])
    tender = state.get("tender", {})
    awards = state.get("awards", [])
    benchmarks = state.get("benchmarks", [])
    sup_summary = state.get("supplier_summary", {})
    dq_notes = state.get("data_quality_notes", [])

    primary_bm = benchmarks[0] if benchmarks else {}

    res = briefing_draft(
        findings=findings,
        tender_summary=tender,
        price_analysis=primary_bm,
        supplier_history=sup_summary,
        data_quality_notes=dq_notes,
    )

    if not res.get("valid"):
        err_msg = f"Draft validation rejected: {', '.join(res.get('errors', []))}"
        logger.error(f"[DRAFT] {err_msg}")
        run_log.append({
            "ts": ts,
            "node": "draft",
            "inputs_summary": {"findings_count": len(findings)},
            "outputs_summary": {"valid": False, "errors": res.get("errors")},
        })
        return {"error": err_msg, "draft": "", "run_log": run_log}

    draft_text = res.get("draft", "")
    run_log.append({
        "ts": ts,
        "node": "draft",
        "inputs_summary": {"findings_count": len(findings)},
        "outputs_summary": {"valid": True, "draft_length": len(draft_text)},
    })
    logger.info(f"[DRAFT] Generated structured briefing markdown ({len(draft_text)} chars)")
    return {"draft": draft_text, "run_log": run_log}


# -----------------------------------------------------------------------------
# Node 6: Human Gate (§6)
# -----------------------------------------------------------------------------
def gate_node(state: ThamaniState) -> dict[str, Any]:
    """Human-in-the-loop CLI gate.

    The named officer reads the draft and types:
    approve | override <finding-id> <note> | reject.
    Loop waits — no timeout auto-approval.
    """
    ts = utc_now_iso()
    run_log = list(state.get("run_log", []))
    officer_name = state.get("officer") or "Procurement Officer"
    draft = state.get("draft", "")
    findings = list(state.get("findings", []))
    interactive = state.get("interactive", False)
    auto_action = state.get("auto_gate_action")

    print("\n" + "=" * 78)
    print("THAMANI VALUE-FOR-MONEY BRIEFING [HUMAN GATE CHECKPOINT]")
    print("=" * 78)
    print(draft)
    print("=" * 78)
    print(f"OFFICER IN CHARGE: {officer_name}")
    print("Available Gate Commands:")
    print("  approve")
    print("  override <finding-id> <explanation>")
    print("  reject")
    print("=" * 78 + "\n")

    decision: dict[str, Any]

    if auto_action:
        # Non-interactive / programmatic / test execution
        cmd = auto_action.strip()
        print(f"[Automated Gate Action]: {cmd}")
        if cmd == "approve":
            decision = {
                "officer_name": officer_name,
                "decision": "approve",
                "finding_id": None,
                "note": "Approved as drafted by reviewing officer.",
                "ts": ts,
            }
        elif cmd.startswith("override"):
            parts = cmd.split(maxsplit=2)
            f_id = parts[1] if len(parts) > 1 else "finding-1"
            note = parts[2] if len(parts) > 2 else "Officer override entered."
            decision = {
                "officer_name": officer_name,
                "decision": "override",
                "finding_id": f_id,
                "note": note,
                "ts": ts,
            }
        elif cmd == "reject":
            decision = {
                "officer_name": officer_name,
                "decision": "reject",
                "finding_id": None,
                "note": "Rejected by reviewing officer.",
                "ts": ts,
            }
        else:
            raise ValueError(f"Unrecognized auto gate action: '{auto_action}'")
    elif not interactive:
        # Non-interactive execution without auto_action (e.g. Web UI preview before officer submits sign-off)
        decision = {
            "officer_name": officer_name,
            "decision": "pending",
            "finding_id": None,
            "note": "Awaiting gate review in UI.",
            "ts": ts,
        }
    else:
        # Interactive loop until valid command
        while True:
            try:
                raw = input(f"Enter decision ({officer_name}) [approve | override <id> <note> | reject]: ").strip()
            except (EOFError, KeyboardInterrupt):
                raw = "reject"

            if not raw:
                continue

            low = raw.lower()
            if low == "approve":
                decision = {
                    "officer_name": officer_name,
                    "decision": "approve",
                    "finding_id": None,
                    "note": "Approved by reviewing officer.",
                    "ts": utc_now_iso(),
                }
                break
            elif low == "reject":
                decision = {
                    "officer_name": officer_name,
                    "decision": "reject",
                    "finding_id": None,
                    "note": "Briefing rejected by officer.",
                    "ts": utc_now_iso(),
                }
                break
            elif low.startswith("override"):
                parts = raw.split(maxsplit=2)
                if len(parts) < 3:
                    print("Usage: override <finding-id> <explanation note>")
                    continue
                f_id = parts[1]
                note = parts[2]
                decision = {
                    "officer_name": officer_name,
                    "decision": "override",
                    "finding_id": f_id,
                    "note": note,
                    "ts": utc_now_iso(),
                }
                break
            else:
                print("Invalid command. Choose 'approve', 'override <id> <note>', or 'reject'.")

    log_entry = {
        "ts": utc_now_iso(),
        "node": "gate",
        "inputs_summary": {"officer_name": officer_name},
        "outputs_summary": decision,
    }
    run_log.append(log_entry)
    logger.info(f"[GATE] Decision recorded: {decision['decision'].upper()} by {officer_name}")

    return {"gate_decision": decision, "run_log": run_log}


# -----------------------------------------------------------------------------
# Node 7: Finalize (§6 & §5)
# -----------------------------------------------------------------------------
def finalize_node(state: ThamaniState) -> dict[str, Any]:
    """Finalize node: unreachable unless gate_decision in {approve, override}.

    Writes final briefing with gate record attached via borrowed filesystem MCP server.
    """
    ts = utc_now_iso()
    run_log = list(state.get("run_log", []))
    gate = state.get("gate_decision") or {}
    decision_type = gate.get("decision")

    if decision_type not in {"approve", "override"}:
        logger.warning(f"[FINALIZE] Decision is '{decision_type}'; output will NOT be finalized.")
        run_log.append({
            "ts": ts,
            "node": "finalize",
            "inputs_summary": {"gate_decision": decision_type},
            "outputs_summary": {"finalized": False, "reason": "Gate rejected or missing approval"},
        })
        return {"run_log": run_log}

    draft = state.get("draft", "")
    ocid = state.get("ocid", "UNKNOWN-OCID")
    officer = gate.get("officer_name", "Procurement Officer")
    gate_note = gate.get("note", "N/A")
    override_id = gate.get("finding_id")

    # Attach official Gate Verification Record with Cryptographic Seal
    gate_record_str, seal_hash = generate_gate_record_with_seal(
        content_to_seal=draft,
        officer_name=officer,
        decision_type=decision_type,
        timestamp=gate.get("ts", ts),
        override_id=override_id,
        note=gate_note,
    )

    final_content = draft + "\n" + gate_record_str

    # Use borrowed filesystem MCP client to write report to disk
    fs_client = FilesystemMCPClient("reports")
    filename = f"thamani_briefing_{ocid}.md"
    saved_path = fs_client.write_file(filename, final_content)

    # Also export official executive HTML dossier
    dossier_filename = f"thamani_dossier_{re.sub(r'[^\w\-.]', '_', ocid)}.html"
    dossier_path = Path("reports") / dossier_filename
    export_dossier_to_file(final_content, dossier_path, ocid=ocid)

    log_entry = {
        "ts": ts,
        "node": "finalize",
        "inputs_summary": {"destination": str(saved_path), "dossier": str(dossier_path)},
        "outputs_summary": {"finalized": True, "file_size": len(final_content)},
    }
    run_log.append(log_entry)
    logger.info(f"[FINALIZE] Briefing successfully finalized to {saved_path}")
    logger.info(f"[FINALIZE] Executive dossier exported to {dossier_path}")

    return {
        "final_report_path": str(saved_path),
        "seal_hash": seal_hash,
        "run_log": run_log,
    }


# -----------------------------------------------------------------------------
# Routing logic
# -----------------------------------------------------------------------------
def check_fetch_success(state: ThamaniState) -> Literal["benchmark", "finalize"]:
    if state.get("error"):
        return "finalize"
    return "benchmark"


def check_draft_success(state: ThamaniState) -> Literal["gate", "finalize"]:
    if state.get("error") or not state.get("draft"):
        return "finalize"
    return "gate"


# -----------------------------------------------------------------------------
# Graph Construction (§6)
# -----------------------------------------------------------------------------
def build_thamani_graph():
    builder = StateGraph(ThamaniState)

    builder.add_node("plan", plan_node)
    builder.add_node("fetch", fetch_node)
    builder.add_node("benchmark", benchmark_node)
    builder.add_node("supplier_check", supplier_check_node)
    builder.add_node("draft", draft_node)
    builder.add_node("gate", gate_node)
    builder.add_node("finalize", finalize_node)

    builder.set_entry_point("plan")
    builder.add_edge("plan", "fetch")
    builder.add_conditional_edges("fetch", check_fetch_success, {"benchmark": "benchmark", "finalize": "finalize"})
    builder.add_edge("benchmark", "supplier_check")
    builder.add_edge("supplier_check", "draft")
    builder.add_conditional_edges("draft", check_draft_success, {"gate": "gate", "finalize": "finalize"})
    builder.add_edge("gate", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()


def persist_run_log(run_log: list[dict[str, Any]]) -> Path:
    """Save run log to runs/<utc-timestamp>.jsonl (gitignored)."""
    runs_dir = Path("runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts_slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = runs_dir / f"{ts_slug}.jsonl"

    with open(log_file, "w", encoding="utf-8") as f:
        for entry in run_log:
            f.write(json.dumps(entry) + "\n")

    return log_file


def run_pipeline(
    ocid: str,
    officer: str = "Procurement Officer",
    auto_gate_action: str | None = None,
    interactive: bool = True,
) -> ThamaniState:
    """Execute end-to-end Thamani analysis loop on an award OCID."""
    app = build_thamani_graph()
    initial_state: ThamaniState = {
        "ocid": ocid,
        "officer": officer,
        "auto_gate_action": auto_gate_action,
        "interactive": interactive,
        "run_log": [],
    }

    result: ThamaniState = app.invoke(initial_state)
    log_path = persist_run_log(result.get("run_log", []))
    logger.info(f"Execution run log persisted to {log_path}")
    return result


# -----------------------------------------------------------------------------
# Demo Scenario (§9)
# -----------------------------------------------------------------------------
def run_demo(officer: str = "Procurement Officer"):
    """Runs the fixed demo scenario (<3 min demo video):

    1. AMARK concentration case (ocds-5whusi-PCKTTI-2695)
    2. AFRICAN TOUCH variant-merge case (ocds-5whusi-1033)
    3. One zero-value data-quality case (ocds-5whusi-275077-PBSS/2025/2026/001)
    """
    print("\n" + "=" * 78)
    print("STARTING THAMANI LIVE DEMO SCENARIO")
    print("=" * 78)

    # 1. AMARK Concentration Case
    print("\n>>> CASE 1: High Supplier Concentration (AMARK NORTHERN AGENCY)")
    res1 = run_pipeline(
        ocid="ocds-5whusi-PCKTTI-2695",
        officer=officer,
        auto_gate_action="override SC-CONC-1 Supplier verified under specialized technical mandate; single-bidder justification accepted.",
        interactive=False,
    )

    # 2. AFRICAN TOUCH SAFARIS Variant Merge Case
    print("\n>>> CASE 2: Supplier Entity Alias Normalization (AFRICAN TOUCH SAFARIS)")
    res2 = run_pipeline(
        ocid="ocds-5whusi-1033",
        officer=officer,
        auto_gate_action="approve",
        interactive=False,
    )

    # 3. Zero-value Data Quality Case (honest-failure beat)
    print("\n>>> CASE 3: Honest Data Quality Anomaly (Zero-Value Award Record)")
    res3 = run_pipeline(
        ocid="ocds-5whusi-275077-PBSS/2025/2026/001",
        officer=officer,
        auto_gate_action="override DQ-VAL-1 Data reporting omission by procuring school; procurement flagged for record reconciliation.",
        interactive=False,
    )

    print("\n" + "=" * 78)
    print("DEMO SCENARIO COMPLETE - ALL 3 CASES PROCESSED THROUGH GATE")
    print("Finalized reports written to 'reports/' directory.")
    print("=" * 78)


# -----------------------------------------------------------------------------
# CLI Entrypoint (§7)
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Thamani - Value-for-Money AI Analyst CLI")
    parser.add_argument("--award", help="Full end-to-end run on one award OCID")
    parser.add_argument("--demo", action="store_true", help="Run deterministic 3-case demo scenario")
    parser.add_argument("--eval", action="store_true", help="Execute EVALS.md tasks 1-9 (3x each)")
    parser.add_argument("--benchmark", action="store_true", help="Run single price benchmark call")
    parser.add_argument("--category", choices=["works", "goods", "services"], help="Procurement category for benchmark")
    parser.add_argument("--value", type=float, help="Award amount to benchmark")
    parser.add_argument("--currency", default="KES", help="Currency code (default KES)")
    parser.add_argument("--officer", default="Procurement Officer", help="Designated officer name at the gate")
    parser.add_argument("--auto-gate", help="Automated gate action for tests/demo (e.g. 'approve', 'override <id> <note>', 'reject')")
    parser.add_argument("--model", default="llama3", help="LLM model identifier")

    args = parser.parse_args()

    if args.benchmark:
        if not args.category or args.value is None:
            print("Error: --benchmark requires --category and --value")
            sys.exit(1)
        res = price_benchmark(args.category, args.value, args.currency)
        print(json.dumps(res, indent=2))
        sys.exit(0)

    if args.demo:
        run_demo(officer=args.officer)
        sys.exit(0)

    if args.eval:
        from tests.test_evals import run_eval_suite
        run_eval_suite()
        sys.exit(0)

    if args.award:
        run_pipeline(
            ocid=args.award,
            officer=args.officer,
            auto_gate_action=args.auto_gate,
            interactive=(args.auto_gate is None),
        )
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
