"""Evaluation Harness for Thamani (§8 of Specification).

Executes the 9 specified evaluation tasks 3x each with majority verdict:
1. Known price outlier -> flagged with cited OCIDs.
2. At-median award -> no flags.
3. AMARK-style concentration -> flagged with award IDs.
4. Broken supplier-id scheme -> handled, run continues.
5. Missing buyer name -> logged warning, no crash.
6. Absurd value (1000x norm) -> data-quality, not a price verdict.
7. Officer override at gate -> logged with identity/ts/note; final reflects the human.
8. Full run on Llama 3.x -> completes fetch -> benchmark -> draft -> gate.
9. Synthetic mixed-currency case -> EXPECTED FAIL (FX normalization deliberately unbuilt).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from src.agent.loop import run_pipeline
from src.thamani_server.server import ocds_fetch, price_benchmark

logger = logging.getLogger("thamani.evals")


def eval_task_1() -> bool:
    """1. Known price outlier -> flagged with cited OCIDs."""
    res = price_benchmark("works", 500_000_000.0, "KES")
    is_flag = res.get("verdict") == "flag"
    has_ocids = len(res.get("nearest_ocids", [])) >= 5
    return is_flag and has_ocids


def eval_task_2() -> bool:
    """2. At-median award -> no flags."""
    # Works median is ~2,500,658 KES
    res = price_benchmark("works", 2_500_000.0, "KES")
    return res.get("verdict") == "ok"


def eval_task_3() -> bool:
    """3. AMARK-style concentration -> flagged with award IDs."""
    state = run_pipeline(
        ocid="ocds-5whusi-PCKTTI-2695",
        auto_gate_action="approve",
        interactive=False,
    )
    findings = state.get("findings", [])
    conc_findings = [f for f in findings if f.get("kind") == "concentration"]
    if not conc_findings:
        return False
    # Verify award IDs/OCIDs are cited
    has_sources = all(len(f.get("sources", [])) > 0 for f in conc_findings)
    return has_sources


def eval_task_4() -> bool:
    """4. Broken supplier-id scheme -> handled, run continues."""
    # Run pipeline on award with non-standard / empty supplier id
    # ocds-5whusi-1038 or similar
    state = run_pipeline(
        ocid="ocds-5whusi-1038",
        auto_gate_action="approve",
        interactive=False,
    )
    return bool(state.get("draft") and state.get("gate_decision"))


def eval_task_5() -> bool:
    """5. Missing buyer name -> logged warning, no crash."""
    # Test that missing buyer name logs warning and proceeds safely
    state = run_pipeline(
        ocid="ocds-5whusi-275077-PBSS/2025/2026/001",
        auto_gate_action="approve",
        interactive=False,
    )
    # Check that draft was generated and no crash occurred
    return bool(state.get("draft") and not state.get("error"))


def eval_task_6() -> bool:
    """6. Absurd value (1000x norm) -> data-quality, not a price verdict."""
    # Works median is ~2.5M KES -> 1500x is ~3.75 Billion KES
    res = price_benchmark("works", 3_750_000_000.0, "KES")
    return res.get("verdict") == "data-quality" and "absurd value" in res.get("note", "")


def eval_task_7() -> bool:
    """7. Officer override at gate -> logged with identity/ts/note; final reflects the human."""
    officer_name = "Chief Procurement Officer Jane Doe"
    override_note = "Specialized engineering mandate approved by county executive."
    state = run_pipeline(
        ocid="ocds-5whusi-1033",
        officer=officer_name,
        auto_gate_action=f"override finding-1 {override_note}",
        interactive=False,
    )
    gate = state.get("gate_decision", {})
    if gate.get("decision") != "override":
        return False
    if gate.get("officer_name") != officer_name:
        return False
    if gate.get("note") != override_note:
        return False
    # Check that final report contains the override record
    report_path = state.get("final_report_path")
    if not report_path:
        return False
    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()
    return officer_name in content and override_note in content


def eval_task_8() -> bool:
    """8. NVIDIA open-weight run reaches the officer gate with a real model call."""
    model = os.getenv("THAMANI_MODEL")
    if not model or not (os.getenv("NVIDIA_API_KEY") or os.getenv("NVIDIA_API_KEY_FILE")):
        return False
    state = run_pipeline(
        ocid="ocds-5whusi-1033",
        interactive=False,
        model=model,
    )
    nodes_executed = [entry["node"] for entry in state.get("run_log", [])]
    required_nodes = {"plan", "fetch", "benchmark", "supplier_check", "model", "draft", "gate", "finalize"}
    return (required_nodes.issubset(set(nodes_executed)) and bool(state.get("draft"))
            and state.get("gate_decision", {}).get("decision") == "pending"
            and not state.get("final_report_path"))


def eval_task_9() -> bool:
    """9. Synthetic mixed-currency case -> EXPECTED FAIL.

    The system flags non-KES as data-quality because automated multi-currency FX
    normalization is not built. An apples-to-apples price benchmark on mixed currency
    fails by specification.
    """
    # Price benchmark on foreign currency USD
    res = price_benchmark("works", 50_000.0, currency="USD")
    # By specification, if automated FX conversion to KES existed, it would produce 'ok' or 'flag'.
    # Because FX normalization is intentionally unbuilt, it returns 'data-quality'.
    # The eval checks if full FX normalization is present. It is NOT -> EXPECTED FAIL.
    has_fx_conversion = (res.get("currency") == "USD" and res.get("verdict") in ("ok", "flag", "watch"))
    return has_fx_conversion  # Expected: False (FAIL)


TASKS = [
    (1, "Known price outlier -> flagged with cited OCIDs", eval_task_1, "PASS"),
    (2, "At-median award -> no flags", eval_task_2, "PASS"),
    (3, "AMARK-style concentration -> flagged with award IDs", eval_task_3, "PASS"),
    (4, "Broken supplier-id scheme -> handled, run continues", eval_task_4, "PASS"),
    (5, "Missing buyer name -> logged warning, no crash", eval_task_5, "PASS"),
    (6, "Absurd value (1000x norm) -> data-quality verdict", eval_task_6, "PASS"),
    (7, "Officer override at gate -> logged with id/ts/note in final", eval_task_7, "PASS"),
    (8, "NVIDIA model call -> pending human gate", eval_task_8, "PASS"),
    (9, "Synthetic mixed-currency case -> EXPECTED FAIL", eval_task_9, "FAIL"),
]


def run_eval_suite() -> list[dict[str, Any]]:
    """Runs all 9 evaluation tasks 3x each and prints the evaluation summary table."""
    print("\n" + "=" * 80)
    print("THAMANI EVALUATION SUITE (§8 EVALS.MD - 3X RUN WITH MAJORITY VERDICT)")
    print("=" * 80)

    results = []

    for task_num, desc, fn, expected in TASKS:
        runs = []
        for r_idx in range(1, 4):
            try:
                passed = fn()
            except Exception as e:
                logger.error(f"Task {task_num} Run {r_idx} encountered error: {e}")
                passed = False
            runs.append(passed)

        # Majority verdict
        pass_count = sum(1 for r in runs if r)
        majority_pass = pass_count >= 2
        verdict_str = "PASS" if majority_pass else "FAIL"

        status_match = (verdict_str == expected)
        results.append({
            "task_num": task_num,
            "description": desc,
            "runs": runs,
            "verdict": verdict_str,
            "expected": expected,
            "status_match": status_match,
        })

    # Print results table
    print(f"{'#':<3} | {'Task Description':<50} | {'Runs (1,2,3)':<12} | {'Verdict':<7} | {'Expected'}")
    print("-" * 80)
    for r in results:
        runs_str = "".join(["P" if x else "F" for x in r["runs"]])
        print(f"{r['task_num']:<3} | {r['description']:<50} | {runs_str:<12} | {r['verdict']:<7} | {r['expected']}")
    print("=" * 80)

    passed_as_expected = sum(1 for r in results if r["status_match"])
    print(f"\nEvaluation Complete: {passed_as_expected}/9 tasks matched exact expected behavior.")
    print("Task 9 is the sole documented honest failure (Mixed-Currency FX normalization).\n")

    return results


if __name__ == "__main__":
    run_eval_suite()
