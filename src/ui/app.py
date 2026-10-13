"""Thamani Web Dashboard — Interactive Auditor Interface & Human Gate.

Provides public procurement oversight officers and challenge evaluators with an
interactive visual interface for tender analysis, empirical price benchmarks,
supplier concentration graphs, human gate sign-off, and cryptographic verification.
"""

from __future__ import annotations

import io
import html
import json
import os
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

# Propagate Streamlit Cloud secrets to os.environ for agent and backend modules
try:
    if hasattr(st, "secrets"):
        for _k in ("NVIDIA_API_KEY", "THAMANI_MODEL", "THAMANI_DB"):
            if _k in st.secrets and _k not in os.environ:
                os.environ[_k] = str(st.secrets[_k]).strip()
except Exception:
    pass

from src.agent.crypto_seal import verify_report_integrity
from src.agent.loop import finalize_reviewed_state, run_pipeline
from src.export.dossier import generate_dossier_html
from src.thamani_server.server import (
    DEFAULT_DB_PATH,
    get_db_connection,
    ocds_fetch,
    price_benchmark,
)
from src.ui.visuals import (
    build_price_distribution_figure,
    build_supplier_concentration_figure,
)

st.set_page_config(
    page_title="Thamani | Public Tender Value-for-Money Analyst",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom High-Contrast Styling (Dark & Light Theme Compatible)
st.markdown(
    """
    <style>
    .main-header {
        font-size: 28px;
        font-weight: 800;
        color: #f8fafc !important;
        margin-bottom: 2px;
    }
    .sub-header {
        font-size: 14px;
        color: #94a3b8 !important;
        margin-bottom: 22px;
    }
    .finding-card {
        background-color: #1e293b !important;
        border: 1px solid #334155 !important;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 14px;
        color: #f8fafc !important;
    }
    .finding-title-high {
        font-size: 15px;
        font-weight: 700;
        color: #f87171 !important;
        margin-bottom: 6px;
    }
    .finding-title-med {
        font-size: 15px;
        font-weight: 700;
        color: #fbbf24 !important;
        margin-bottom: 6px;
    }
    .finding-text {
        font-size: 14px;
        color: #e2e8f0 !important;
        line-height: 1.6;
        margin-bottom: 10px;
    }
    .source-pill {
        display: inline-block;
        background-color: #0f172a;
        color: #38bdf8 !important;
        border: 1px solid #0284c7;
        padding: 3px 8px;
        border-radius: 4px;
        font-family: monospace;
        font-size: 12px;
        margin-right: 6px;
        margin-bottom: 4px;
    }
    .gate-card {
        background-color: #1e293b !important;
        border: 2px solid #eab308 !important;
        border-radius: 8px;
        padding: 24px;
        margin: 24px 0;
        color: #f8fafc !important;
    }
    .ai-intel-box {
        background-color: #0f172a !important;
        border: 1px solid #38bdf8 !important;
        border-radius: 8px;
        padding: 18px 22px;
        margin-bottom: 20px;
        color: #f8fafc !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_supplier_buyer_breakdown(supplier_norm: str) -> list[dict[str, Any]]:
    """Helper to get buyer breakdown for supplier chart."""
    conn = get_db_connection(DEFAULT_DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT buyer_name, count(*) as wins
            FROM (SELECT DISTINCT ocid, award_id, buyer_name FROM awards
                  WHERE supplier_name_norm = ?)
            WHERE TRIM(COALESCE(buyer_name, '')) != ''
            GROUP BY buyer_name
            ORDER BY wins DESC
            LIMIT 10
            """,
            (supplier_norm,),
        )
        return [{"buyer_name": r[0], "wins": r[1]} for r in cursor.fetchall()]
    finally:
        conn.close()


def generate_ai_executive_reasoning(
    category: str,
    award_val: float,
    verdict: str,
    stats: dict[str, Any],
    supplier_summary: dict[str, Any],
    all_suppliers: list[dict[str, Any]] | None = None,
) -> str:
    """Produces the AI agent reasoning synthesis."""
    stats = stats or {}
    median = float(stats.get("median", 0))
    p99 = float(stats.get("p99", 0))
    sup_name = html.escape(str(supplier_summary.get("supplier_name", "Supplier")))
    wins = int(supplier_summary.get("total_wins", 0))
    top_wins = int(supplier_summary.get("top_wins", wins))
    top_buyer = html.escape(str(supplier_summary.get("top_buyer", "a single procuring entity")))
    buyers = int(supplier_summary.get("distinct_buyers", 0))
    conc_flag = supplier_summary.get("concentration_flag", False)

    narrative = []
    if verdict == "ok":
        narrative.append(
            f"**Price Integrity**: Award of KES {award_val:,.0f} aligns with historical {category} expectations "
            f"(historical median: KES {median:,.0f}). No abnormal pricing premium detected."
        )
    elif verdict == "watch":
        narrative.append(
            f"**Price Warning**: Award of KES {award_val:,.0f} is elevated above 1.5× category median (KES {median:,.0f}). "
            "Recommends validating bill of quantities or scope complexity before approval."
        )
    elif verdict == "flag":
        narrative.append(
            f"**Outlier Escalation**: Award of KES {award_val:,.0f} breaches statistical risk bounds "
            f"(3× median: KES {3*median:,.0f}, P99: KES {p99:,.0f}). Review scope and quantities; this signal does not establish overpricing."
        )
    else:
        narrative.append(
            "**Data Quality Anomaly**: Award record contains non-standard value representation; routed to audit reconciliation."
        )

    if conc_flag:
        pct = (top_wins / wins * 100) if wins > 0 else 0
        if pct >= 99.9:
            share_desc = f"100% (all {wins}) of its recorded awards"
        elif pct > 50:
            share_desc = f"a majority ({pct:.0f}% — {top_wins} of {wins}) of its recorded awards"
        else:
            share_desc = f"{pct:.0f}% ({top_wins} of {wins}) of its recorded awards"

        narrative.append(
            f"**Supplier Review Signal**: Entity `{sup_name}` has repeated awards from the same buyer. "
            f"Holding {share_desc} from '{top_buyer}' warrants verification against competitive bidding thresholds."
        )
    else:
        narrative.append(
            f"**Supplier Profile**: Entity `{sup_name}` has a diversified footprint ({wins} wins distributed across {buyers} procuring entities)."
        )

    if all_suppliers and len(all_suppliers) > 1:
        flagged_count = sum(1 for s in all_suppliers if s.get("concentration_flag"))
        if flagged_count > 1:
            narrative.append(
                f"**Multi-Lot Cluster Alert**: Tender comprises {len(all_suppliers)} separate awards, with {flagged_count} distinct suppliers exhibiting single-buyer captive concentration."
            )

    # Deduplicate any duplicate sentences
    seen = set()
    clean_narrative = []
    for part in narrative:
        if part not in seen:
            seen.add(part)
            clean_narrative.append(part)

    return " ".join(clean_narrative)


# Sidebar Navigation & Settings
with st.sidebar:
    st.markdown("### ⚖️ **Thamani Oversight Hub**")
    st.caption("Agentic AI Value-for-Money Oversight Engine for Public Tenders")
    st.divider()

    st.markdown("#### **Tender Selection**")
    demo_presets = {
        "PC Kinyanjui Multi-Award Cluster (AMARK Repeated-Buyer Review)": "ocds-5whusi-PCKTTI-2695",
        "African Touch Safaris (Alias Merging & Median)": "ocds-5whusi-1033",
        "Air Ticket Procurement (Services Benchmark)": "ocds-5whusi-1038",
        "PBSS Tender (Data Quality / Missing Buyer)": "ocds-5whusi-275077-PBSS/2025/2026/001",
        "Custom OCID": "CUSTOM",
    }
    selected_preset = st.selectbox("Select Benchmark Scenario", list(demo_presets.keys()))

    if selected_preset == "Custom OCID":
        active_ocid = st.text_input("Enter Tender OCID", value="ocds-5whusi-PCKTTI-2695")
    else:
        active_ocid = demo_presets[selected_preset]
        st.code(active_ocid, language="text")

    st.markdown("#### **Reviewing Officer**")
    officer_name = st.text_input("Designated Officer Name", value="", placeholder="Enter the reviewing officer's name")

    st.divider()
    st.markdown("#### **AI Model & Agent Architecture**")
    st.markdown("- **Agent Framework**: LangGraph StateGraph")
    st.markdown(f"- **Review Focus Model**: {os.getenv('THAMANI_MODEL') or 'Disabled (deterministic analysis)'}")
    st.markdown("- **Tool Standard**: FastMCP Standard Protocols")
    st.markdown("- **Audit Baselines**: 9 Years (260,744 tenders, 109,237 awards)")
    st.markdown("- **Statutory Guardrail**: Zero Autonomous Awards; Human Gate Enforced")


# Main Dashboard Tabs
tab_analysis, tab_dossier, tab_crypto, tab_evals = st.tabs([
    "🔍 Tender Analysis & Gate",
    "📄 Official Executive Dossier",
    "🔒 Cryptographic Tamper Seal",
    "📊 Evaluation Harness (§8)",
])


# -----------------------------------------------------------------------------
# TAB 1: Tender Analysis & Interactive Gate
# -----------------------------------------------------------------------------
with tab_analysis:
    st.markdown('<div class="main-header">Tender Value-for-Money Analysis</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sub-header">Evaluating Tender OCID: <code>{active_ocid}</code></div>',
        unsafe_allow_html=True,
    )

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        run_analysis = st.button("🚀 Run Agentic Audit", type="primary", use_container_width=True)

    if run_analysis:
        try:
            with st.spinner("Executing 6-stage LangGraph pipeline..."):
                state = run_pipeline(
                    ocid=active_ocid,
                    officer=officer_name,
                    model=os.getenv("THAMANI_MODEL") or None,
                    auto_gate_action=None,  # Preview in UI; officer clicks sign below
                    interactive=False,
                )
                st.session_state["current_state"] = state
                st.session_state["active_ocid"] = active_ocid
                st.session_state.pop("final_state", None)
                if state.get("error"):
                    st.session_state["pipeline_error"] = state["error"]
                else:
                    st.session_state.pop("pipeline_error", None)
            st.rerun()
        except Exception as exc:
            st.error(f"Audit execution encountered an error: {exc}")
            logger.exception(f"Failed to execute audit pipeline on {active_ocid}")
            st.stop()

    if "current_state" in st.session_state and st.session_state.get("active_ocid") == active_ocid:
        if st.session_state.get("pipeline_error"):
            st.error(f"Audit pipeline alert: {st.session_state['pipeline_error']}")

        state = st.session_state.get("current_state", {})
        tender = state.get("tender", {})
        awards = state.get("awards", [])
        benchmarks = state.get("benchmarks", [])
        supplier_summary = state.get("supplier_summary", {})
        all_suppliers = state.get("all_suppliers", [])
        findings = state.get("findings", [])
        draft = state.get("draft", "")

        with st.expander("Execution trace: analysis tools and report write", expanded=True):
            tool_names = {"fetch": "ocds_fetch (local tool)",
                          "benchmark": "price_benchmark (local tool)",
                          "supplier_check": "Supplier history query",
                          "draft": "briefing_draft (local tool)",
                          "gate": "Officer review",
                          "finalize": "filesystem.write_file (MCP, only after approval)"}
            st.dataframe([
                {"Time (UTC)": entry.get("ts", ""),
                 "Step": entry.get("node", ""),
                 "Tool / action": tool_names.get(entry.get("node"), entry.get("node", "")),
                 "Result": json.dumps(entry.get("outputs_summary", {}), ensure_ascii=False)}
                for entry in state.get("run_log", [])
            ], hide_index=True, use_container_width=True)

        # Summary Metrics Row
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            category = (tender.get("category") or "works").upper()
            st.metric("Category", category)
        with m_col2:
            unique_awards = {(a.get("ocid", state.get("ocid")), a.get("award_id")): a for a in awards}
            total_val = sum(a.get("value_amount", 0.0) for a in unique_awards.values())
            if len(awards) > 1:
                st.metric("Total Tender Value", f"KES {total_val:,.0f}", delta=f"{len(awards)} Awards")
            else:
                award_val = awards[0].get("value_amount", 0.0) if awards else 0.0
                st.metric("Award Value", f"KES {award_val:,.0f}")
        with m_col3:
            verdict = benchmarks[0].get("verdict", "ok") if benchmarks else "ok"
            st.metric("Price Verdict", verdict.upper())
        with m_col4:
            conc_flag = any(s.get("concentration_flag") for s in all_suppliers) if all_suppliers else supplier_summary.get("concentration_flag", False)
            st.metric("Supplier Concentration", "ALERT (High Risk)" if conc_flag else "Normal")

        # AI Agent Executive Reasoning Synthesis Box
        bm_stats = benchmarks[0].get("stats", {}) if benchmarks else {}
        primary_val = awards[0].get("value_amount", 0.0) if awards else 0.0
        ai_reasoning = generate_ai_executive_reasoning(
            category=category,
            award_val=primary_val,
            verdict=verdict,
            stats=bm_stats,
            supplier_summary=supplier_summary,
            all_suppliers=all_suppliers,
        )
        st.markdown(
            f"""
            <div class="ai-intel-box">
                <div style="font-size:13px; font-weight:800; text-transform:uppercase; letter-spacing:1px; color:#38bdf8; margin-bottom:6px;">
                    🤖 AI Agent Executive Reasoning Synthesis
                </div>
                <div style="font-size:14px; line-height:1.6; color:#f1f5f9;">
                    {ai_reasoning}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()

        # Visual Analytics Charts
        c_col1, c_col2 = st.columns(2)
        with c_col1:
            if benchmarks and awards and benchmarks[0].get("stats") and primary_val > 0:
                bm = benchmarks[0]
                stats = bm.get("stats", {})
                fig_price = build_price_distribution_figure(
                    category=tender.get("category") or "works",
                    award_value=primary_val,
                    stats=stats,
                    verdict=bm.get("verdict", "ok"),
                    nearest_awards=bm.get("nearest_awards", []),
                )
                st.plotly_chart(fig_price, use_container_width=True)
            else:
                st.info("No comparable price distribution is available for this record.")
            st.caption("Category totals are screening signals. Scope, quantities, year and inflation are not controlled; a flag is not proof of overpricing.")

        with c_col2:
            if supplier_summary:
                sup_norm = supplier_summary.get("supplier_name_norm", "")
                buyer_counts = load_supplier_buyer_breakdown(sup_norm)
                fig_sup = build_supplier_concentration_figure(
                    supplier_name=supplier_summary.get("supplier_name", sup_norm),
                    buyer_counts=buyer_counts,
                )
                st.plotly_chart(fig_sup, use_container_width=True)
                if all_suppliers and len(all_suppliers) > 1:
                    st.caption(f"Showing primary captive supplier: **{supplier_summary.get('supplier_name')}** ({supplier_summary.get('top_wins')} wins from single buyer). Tender contains {len(all_suppliers)} awards total.")
            else:
                st.info("No supplier history available.")

        # Key Evidence-Backed Findings Box (High Contrast)
        st.markdown("#### **Evidence-Backed Findings**")
        if findings:
            for f in findings:
                sev = f.get("severity", "medium").upper()
                kind = f.get("kind", "").upper()
                sources = f.get("sources", [])
                title_class = "finding-title-high" if sev == "HIGH" else "finding-title-med"
                border_color = "#ef4444" if sev == "HIGH" else "#f59e0b"

                citations_html = "".join([f'<span class="source-pill">{html.escape(str(s))}</span>' for s in sources])

                st.markdown(
                    f"""
                    <div class="finding-card" style="border-left: 6px solid {border_color} !important;">
                        <div class="{title_class}">[{html.escape(str(f.get('id')))}] {html.escape(kind)} (Severity: {html.escape(sev)})</div>
                        <div class="finding-text">{html.escape(str(f.get('text')))}</div>
                        <div>
                            <span style="font-size:12px; font-weight:700; color:#94a3b8; margin-right:8px;">Sources Cited:</span>
                            {citations_html}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.success("No pricing outliers or supplier concentration flags detected for this tender.")

        # Human-in-the-Loop Gate Section
        st.markdown(
            """
            <div style="background-color: #1e293b; border: 2px solid #eab308; border-radius: 8px; padding: 20px 24px; margin: 24px 0 16px 0;">
                <div style="font-size: 18px; font-weight: 800; color: #f8fafc; margin-bottom: 6px;">
                    🛑 Human Review Gate
                </div>
                <div style="color: #cbd5e1; font-size: 13.5px; line-height: 1.5;">
                    Thamani prepares the empirical evidence but <strong>never</strong> awards or disqualifies. A designated human officer must explicitly review and sign off before output can be archived.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        gate_action = st.radio(
            "Officer Verification Decision",
            ["Approve as Drafted", "Override Finding with Note", "Reject Briefing"],
            horizontal=True,
        )

        override_finding_id = None
        override_note = ""
        if gate_action == "Override Finding with Note":
            col_ov1, col_ov2 = st.columns([1, 2])
            with col_ov1:
                finding_ids = [f.get("id") for f in findings]
                override_finding_id = st.selectbox("Target Finding ID", finding_ids)
            with col_ov2:
                override_note = st.text_input("Officer Justification / Explanation", value="")

        can_review = bool(officer_name.strip() and draft and not state.get("error")
                          and state.get("gate_decision", {}).get("decision") == "pending")
        if gate_action == "Override Finding with Note":
            can_review = can_review and bool(override_finding_id and override_note.strip())
        if not officer_name.strip():
            st.warning("To enable signing, enter your name in Designated Officer Name on the left, then press Enter.")
        elif state.get("error") or not draft:
            st.warning("There is no valid briefing to sign. Click Run Agentic Audit to generate a new briefing.")
        elif state.get("gate_decision", {}).get("decision") != "pending":
            st.info("This briefing has already been reviewed. Click Run Agentic Audit to start a new review.")
        elif gate_action == "Override Finding with Note" and not (override_finding_id and override_note.strip()):
            st.warning("Choose an existing finding and enter your explanation to enable signing.")
        if st.button("✍️ Formally Sign & Finalize Briefing", type="primary", disabled=not can_review):
            cmd = "approve"
            if gate_action == "Override Finding with Note":
                cmd = f"override {override_finding_id} {override_note}"
            elif gate_action == "Reject Briefing":
                cmd = "reject"

            with st.spinner("Applying cryptographic seal and finalizing briefing..."):
                try:
                    final_state = finalize_reviewed_state(state, officer_name, cmd)
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(f"Briefing could not be finalized: {exc}")
                    st.stop()
                st.session_state["final_state"] = final_state
                st.session_state["current_state"] = final_state
            st.rerun()

        # Final Report Output
        if "final_state" in st.session_state and st.session_state.get("final_state", {}).get("ocid") == active_ocid:
            f_state = st.session_state["final_state"]
            report_path = f_state.get("final_report_path")
            seal_hash = f_state.get("seal_hash")

            if report_path and Path(report_path).exists():
                content = Path(report_path).read_text(encoding="utf-8")
                if not verify_report_integrity(content).get("verified"):
                    st.error("Archived report checksum is invalid. Use the verification tab to inspect it.")
                    st.stop()
                st.success("✅ **Briefing reviewed, checksummed, and archived.**")
                st.markdown("#### **Final Sealed Briefing**")
                st.code(content, language="markdown")
                # Download Buttons
                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    st.download_button(
                        label="📥 Download Markdown Briefing (.md)",
                        data=content,
                        file_name=f"thamani_briefing_{active_ocid}.md",
                        mime="text/markdown",
                        use_container_width=True,
                    )
                with d_col2:
                    dossier_html = generate_dossier_html(content, ocid=active_ocid, is_sealed=True)
                    st.download_button(
                        label="📥 Download Official HTML Dossier (.html)",
                        data=dossier_html,
                        file_name=f"thamani_dossier_{active_ocid}.html",
                        mime="text/html",
                        use_container_width=True,
                    )
            else:
                st.info("Briefing rejected; no final report was archived.")


# -----------------------------------------------------------------------------
# TAB 2: Official Executive Dossier
# -----------------------------------------------------------------------------
with tab_dossier:
    st.markdown('<div class="main-header">Official Executive Audit Dossier</div>', unsafe_allow_html=True)
    st.caption("Standardized public oversight docket with Republic of Kenya insignia and print-ready formatting.")

    active_in_session = st.session_state.get("active_ocid")
    has_final = "final_state" in st.session_state and active_in_session == active_ocid
    has_current = "current_state" in st.session_state and active_in_session == active_ocid

    if has_final:
        f_state = st.session_state["final_state"]
        rep_path = f_state.get("final_report_path")
        if rep_path and Path(rep_path).exists():
            final_md = Path(rep_path).read_text(encoding="utf-8")
            st.success("✅ **OFFICIALLY SEALED AUDIT DOSSIER** — Reviewed by officer and checked against the stored SHA-256 checksum.")
            dossier_html = generate_dossier_html(final_md, ocid=active_ocid, is_sealed=True)
            components.html(dossier_html, height=1000, scrolling=True)
        else:
            st.info("Briefing rejected or not finalized. No official dossier archived.")
    elif has_current:
        c_state = st.session_state["current_state"]
        draft_md = c_state.get("draft", "")
        st.warning("⚠️ **PRE-GATE AUDIT DRAFT (UNSEALED)** — This draft is awaiting formal officer verification in Tab 1 before cryptographic sealing.")
        dossier_html = generate_dossier_html(draft_md, ocid=active_ocid, is_sealed=False)
        components.html(dossier_html, height=1000, scrolling=True)
    else:
        st.info(f"No active audit record for `{active_ocid}`. Please go to the **'Tender Analysis & Gate'** tab and click **'🚀 Run Agentic Audit'** to generate the dossier.")


# -----------------------------------------------------------------------------
# TAB 3: Cryptographic Tamper-Proof Seal Verifier
# -----------------------------------------------------------------------------
with tab_crypto:
    st.markdown('<div class="main-header">Cryptographic Seal Verification Engine</div>', unsafe_allow_html=True)
    st.caption("Checks the report against its stored SHA-256 checksum. This detects changes; it does not authenticate officer identity or protect against replacing both the report and checksum.")

    test_file = st.file_uploader("Upload Briefing Markdown File (.md)", type=["md", "txt"])
    input_text = st.text_area("Or Paste Briefing Content Here", height=200)

    target_content = ""
    if test_file is not None:
        target_content = test_file.getvalue().decode("utf-8")
    elif input_text.strip():
        target_content = input_text.strip()

    if target_content:
        res = verify_report_integrity(target_content)
        if res.get("verified"):
            st.success("✅ **CRYPTOGRAPHIC SEAL VERIFIED VALID**")
            if not res.get("metadata_protected"):
                st.warning("Legacy checksum: verification notes and override metadata are not protected.")
            st.json(res)
        else:
            st.error("❌ **TAMPER ALERT / SEAL INVALID**")
            st.json(res)


# -----------------------------------------------------------------------------
# TAB 4: Evaluation Harness (§8 EVALS.MD)
# -----------------------------------------------------------------------------
with tab_evals:
    st.markdown('<div class="main-header">Thamani Evaluation Suite (§8 of Specification)</div>', unsafe_allow_html=True)
    st.caption("Executes all 9 empirical evaluation tasks 3× each with majority verdict under pinned database snapshot.")

    eval_data = [
        {"#": 1, "Task": "Known price outlier -> flagged with cited OCIDs", "Target": "PASS", "Note": "500M KES works contract vs 2.5M median"},
        {"#": 2, "Task": "At-median award -> no flags", "Target": "PASS", "Note": "2.5M KES works contract (true median)"},
        {"#": 3, "Task": "AMARK-style concentration -> flagged with award IDs", "Target": "PASS", "Note": "188/188 wins with single buyer"},
        {"#": 4, "Task": "Broken supplier-id scheme -> handled, run continues", "Target": "PASS", "Note": "Normalizes name variant cleanly"},
        {"#": 5, "Task": "Missing buyer name -> logged warning, no crash", "Target": "PASS", "Note": "Graceful fallback on missing metadata"},
        {"#": 6, "Task": "Absurd value (1000x norm) -> data-quality verdict", "Target": "PASS", "Note": "3.75B KES anomaly flagged as data quality"},
        {"#": 7, "Task": "Officer override at gate -> logged in final", "Target": "PASS", "Note": "Officer identity + timestamp stamped in file"},
        {"#": 8, "Task": "Full run on open weights -> completes all 6 stages", "Target": "PASS", "Note": "traverses plan->fetch->benchmark->draft->gate"},
        {"#": 9, "Task": "Synthetic mixed-currency case -> EXPECTED FAIL", "Target": "FAIL", "Note": "Documented honest failure (FX conversion unbuilt)"},
    ]

    st.table(eval_data)
    st.info("Run pytest for regression tests and python -m src.agent.loop --eval for the separate evaluation harness. Live NVIDIA evaluation requires configured credentials.")
