"""Thamani FastMCP Server.

Exposes the 3 core analysis tools:
1. ocds_fetch: Look up OCID records and award details from local SQLite cache.
2. price_benchmark: Statistical price outlier detection against category history.
3. briefing_draft: Validates structural citations and assembles Markdown briefing.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import statistics
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
)
logger = logging.getLogger("thamani.server")

DEFAULT_DB_PATH = Path(os.environ.get("THAMANI_DB", "data/thamani.sqlite"))

mcp = FastMCP("thamani-server")


def get_db_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a read-only or read-write SQLite connection with WAL mode."""
    target = Path(db_path or DEFAULT_DB_PATH)
    if not target.exists():
        gz_target = target.with_name(target.name + ".gz")
        if gz_target.exists():
            import gzip
            import shutil
            logger.info(f"Extracting compressed database {gz_target} to {target}...")
            target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(gz_target, "rb") as f_in, open(target, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        else:
            raise FileNotFoundError(f"Thamani database not found at {target}. Run ocds.py first.")
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    return conn


# -----------------------------------------------------------------------------
# Tool 1: ocds_fetch
# -----------------------------------------------------------------------------
@mcp.tool()
def ocds_fetch(ocid: str, db_path: str | None = None) -> dict[str, Any]:
    """Look up an OCID in SQLite.

    Returns the tender details, list of associated awards with values and
    normalized suppliers, and each record's OCID as its source reference.
    Raises ValueError if unknown.
    """
    ocid = ocid.strip()
    if not ocid:
        raise ValueError("OCID parameter must not be empty.")

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()

        # Find tender
        cursor.execute(
            """
            SELECT ocid, tender_id, title, procurement_method, category,
                   buyer_id, buyer_name, record_date
            FROM tenders
            WHERE ocid = ?
            """,
            (ocid,),
        )
        t_row = cursor.fetchone()

        # Find awards for this OCID
        cursor.execute(
            """
            SELECT id, ocid, award_id, award_date, value_amount, value_currency,
                   supplier_id, supplier_name, supplier_name_norm, buyer_id, buyer_name
            FROM awards
            WHERE ocid = ?
            """,
            (ocid,),
        )
        a_rows = cursor.fetchall()

        # If not found directly by tender OCID, check if OCID is an award's OCID or award_id
        if not t_row and not a_rows:
            cursor.execute(
                """
                SELECT ocid FROM awards WHERE award_id = ? LIMIT 1
                """,
                (ocid,),
            )
            fallback = cursor.fetchone()
            if fallback:
                resolved_ocid = fallback["ocid"]
                return ocds_fetch(resolved_ocid, db_path)

            raise ValueError(
                f"Unknown OCID: '{ocid}'. Tender or award record not found in local OCDS cache."
            )

        awards_list = []
        for r in a_rows:
            awards_list.append({
                "id": r["id"],
                "ocid": r["ocid"],
                "award_id": r["award_id"],
                "award_date": r["award_date"],
                "value_amount": float(r["value_amount"]) if r["value_amount"] is not None else 0.0,
                "value_currency": r["value_currency"] or "KES",
                "supplier_id": r["supplier_id"] or "",
                "supplier_name": r["supplier_name"] or "",
                "supplier_name_norm": r["supplier_name_norm"] or "",
                "buyer_id": r["buyer_id"] or "",
                "buyer_name": r["buyer_name"] or "",
                "source_ref": r["ocid"],
            })

        tender_dict: dict[str, Any]
        if t_row:
            tender_dict = {
                "ocid": t_row["ocid"],
                "tender_id": t_row["tender_id"] or "",
                "title": t_row["title"] or "",
                "procurement_method": t_row["procurement_method"] or "",
                "category": (t_row["category"] or "").lower(),
                "buyer_id": t_row["buyer_id"] or "",
                "buyer_name": t_row["buyer_name"] or "",
                "record_date": t_row["record_date"] or "",
                "source_ref": t_row["ocid"],
            }
        else:
            # Synthetic tender dict from award records
            first_aw = awards_list[0] if awards_list else {}
            tender_dict = {
                "ocid": ocid,
                "tender_id": "",
                "title": f"Procurement Record {ocid}",
                "procurement_method": "open",
                "category": "goods",
                "buyer_id": first_aw.get("buyer_id", ""),
                "buyer_name": first_aw.get("buyer_name", ""),
                "record_date": first_aw.get("award_date", ""),
                "source_ref": ocid,
            }

        return {
            "ocid": ocid,
            "source_ref": ocid,
            "tender": tender_dict,
            "awards": awards_list,
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Tool 2: price_benchmark
# -----------------------------------------------------------------------------
def _percentile(data: list[float], p: float) -> float:
    """Compute percentile for sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(data):
        return float(data[-1])
    d0 = data[f] * (c - k)
    d1 = data[c] * (k - f)
    return float(d0 + d1)


# In-memory category values cache for fast repeated benchmark evaluations
_CATEGORY_CACHE: dict[str, list[float]] = {}


def _get_category_values(conn: sqlite3.Connection, category: str) -> list[float]:
    """Retrieve or cache sorted values for category."""
    cat = category.strip().lower()
    if cat in _CATEGORY_CACHE:
        return _CATEGORY_CACHE[cat]

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT a.value_amount
        FROM awards a
        JOIN tenders t ON a.ocid = t.ocid
        WHERE t.category = ? COLLATE NOCASE AND a.value_amount > 0
        ORDER BY a.value_amount ASC
        """,
        (cat,),
    )
    rows = cursor.fetchall()
    values = [float(r[0]) for r in rows]
    _CATEGORY_CACHE[cat] = values
    return values


@mcp.tool()
def price_benchmark(
    category: str,
    value_amount: float,
    currency: str = "KES",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Compare award value against historical category baseline in SQLite.

    Returns stats (n, median, p25, p75, p99), verdict (ok | watch | flag | data-quality),
    and cited OCIDs of the 5 nearest historical awards as evidence.
    """
    cat = (category or "").strip().lower()
    curr = (currency or "KES").strip().upper()

    # Rule: non-positive value
    if value_amount is None or value_amount <= 0:
        return {
            "category": cat,
            "value_amount": value_amount,
            "currency": curr,
            "verdict": "data-quality",
            "note": "non-positive award value",
            "stats": None,
            "nearest_ocids": [],
            "evidence_ocids": [],
        }

    # Rule: non-KES currency
    if curr != "KES":
        return {
            "category": cat,
            "value_amount": value_amount,
            "currency": curr,
            "verdict": "data-quality",
            "note": f"currency {curr} not comparable to KES history",
            "stats": None,
            "nearest_ocids": [],
            "evidence_ocids": [],
        }

    conn = get_db_connection(db_path)
    try:
        values = _get_category_values(conn, cat)
        if not values:
            return {
                "category": cat,
                "value_amount": value_amount,
                "currency": curr,
                "verdict": "data-quality",
                "note": f"no historical awards found for category '{cat}'",
                "stats": None,
                "nearest_ocids": [],
                "evidence_ocids": [],
            }

        n = len(values)
        median = float(statistics.median(values))
        p25 = _percentile(values, 25)
        p75 = _percentile(values, 75)
        p99 = _percentile(values, 99)

        # 5 nearest awards by absolute value
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.ocid, a.value_amount
            FROM awards a
            JOIN tenders t ON a.ocid = t.ocid
            WHERE t.category = ? COLLATE NOCASE AND a.value_amount > 0
            ORDER BY ABS(a.value_amount - ?) ASC
            LIMIT 5
            """,
            (cat, value_amount),
        )
        nearest_rows = cursor.fetchall()
        nearest_ocids = [r["ocid"] for r in nearest_rows]

        # Rule: Absurd value (>1000x median norm) gets data-quality flag (Task 6 in EVALS.md)
        if value_amount > 1000.0 * median:
            verdict = "data-quality"
            note = f"absurd value ({value_amount:,.0f} KES is >1000x category median {median:,.0f} KES)"
        elif value_amount > p99 or value_amount > 3.0 * median:
            verdict = "flag"
            note = f"value exceeds p99 ({p99:,.0f} KES) or 3x median ({3.0 * median:,.0f} KES)"
        elif value_amount > 1.5 * median:
            verdict = "watch"
            note = f"value exceeds 1.5x median ({1.5 * median:,.0f} KES)"
        else:
            verdict = "ok"
            note = f"value within normal historical distribution (median: {median:,.0f} KES)"

        return {
            "category": cat,
            "value_amount": value_amount,
            "currency": curr,
            "verdict": verdict,
            "note": note,
            "stats": {
                "n": n,
                "median": median,
                "p25": p25,
                "p75": p75,
                "p99": p99,
            },
            "nearest_ocids": nearest_ocids,
            "evidence_ocids": nearest_ocids,
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Tool 3: briefing_draft
# -----------------------------------------------------------------------------
FORBIDDEN_PATTERNS = [
    r"\bwinner\b",
    r"\bshould select\b",
    r"\brecommend awarding\b",
    r"\bshould award\b",
    r"\brecommend award\b",
    r"\brecommended award\b",
    r"\baward to\b",
    r"\bselect supplier\b",
]


def validate_findings(findings: list[dict[str, Any]]) -> list[str]:
    """Validate that every finding conforms to the strict structural contract."""
    errors = []
    if not isinstance(findings, list):
        return ["Findings must be a list of dictionaries."]

    valid_kinds = {"price-outlier", "concentration", "data-quality"}
    valid_severities = {"high", "medium", "low"}

    for idx, f in enumerate(findings):
        f_id = f.get("id") or f"finding-{idx+1}"
        kind = f.get("kind")
        severity = f.get("severity")
        text = f.get("text")
        sources = f.get("sources")

        if not text or not str(text).strip():
            errors.append(f"Finding '{f_id}': missing or empty text.")

        if not sources or not isinstance(sources, list) or len(sources) == 0:
            errors.append(f"Finding '{f_id}': missing source citations (sources must be a non-empty list of OCIDs).")
        else:
            for s in sources:
                if not s or not str(s).strip():
                    errors.append(f"Finding '{f_id}': contains an empty source citation.")

        if kind not in valid_kinds:
            errors.append(f"Finding '{f_id}': invalid kind '{kind}'. Must be one of {sorted(valid_kinds)}.")

        if severity not in valid_severities:
            errors.append(f"Finding '{f_id}': invalid severity '{severity}'. Must be one of {sorted(valid_severities)}.")

        # Check for forbidden recommendation language in finding text
        t_lower = str(text or "").lower()
        for pat in FORBIDDEN_PATTERNS:
            if re.search(pat, t_lower):
                errors.append(f"Finding '{f_id}' contains forbidden outcome/recommendation phrasing matching '{pat}'.")

    return errors


@mcp.tool()
def briefing_draft(
    findings: list[dict[str, Any]],
    tender_summary: dict[str, Any] | None = None,
    price_analysis: dict[str, Any] | None = None,
    supplier_history: dict[str, Any] | None = None,
    data_quality_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble a markdown briefing with structural citation enforcement.

    Refuses to draft if any finding lacks sources or contains forbidden recommendation language.
    Produces required sections:
    - Award summary
    - Price analysis
    - Supplier history
    - Data-quality notes
    - Officer decision (left blank for human gate)
    """
    errors = validate_findings(findings)
    if errors:
        return {
            "valid": False,
            "errors": errors,
            "draft": "",
        }

    # Safe defaults
    tender_summary = tender_summary or {}
    price_analysis = price_analysis or {}
    supplier_history = supplier_history or {}
    data_quality_notes = data_quality_notes or []

    ocid = tender_summary.get("ocid", "UNKNOWN-OCID")
    title = tender_summary.get("title", "Procurement Case Analysis")
    category = tender_summary.get("category", "Unspecified").upper()
    buyer = tender_summary.get("buyer_name", "Unspecified Buyer")

    md_lines: list[str] = []
    md_lines.append(f"# Value-for-Money Analysis Briefing: {ocid}")
    md_lines.append("")

    # Section 1: Award summary
    md_lines.append("## Award summary")
    md_lines.append(f"- **Tender OCID**: `{ocid}`")
    md_lines.append(f"- **Title**: {title}")
    md_lines.append(f"- **Procurement Category**: {category}")
    md_lines.append(f"- **Procuring Entity (Buyer)**: {buyer}")
    if "value_amount" in tender_summary:
        val = tender_summary.get("value_amount", 0.0)
        curr = tender_summary.get("value_currency", "KES")
        md_lines.append(f"- **Recorded Value**: {val:,.2f} {curr}")
    md_lines.append("")

    # Section 2: Price analysis
    md_lines.append("## Price analysis")
    if price_analysis:
        verdict = price_analysis.get("verdict", "N/A").upper()
        md_lines.append(f"- **Verdict**: `{verdict}`")
        if "note" in price_analysis:
            md_lines.append(f"- **Assessment**: {price_analysis['note']}")
        stats = price_analysis.get("stats")
        if stats:
            md_lines.append(
                f"- **Baseline Statistics** (n={stats.get('n', 0):,}): "
                f"Median = {stats.get('median', 0.0):,.2f} KES, "
                f"P25 = {stats.get('p25', 0.0):,.2f} KES, "
                f"P75 = {stats.get('p75', 0.0):,.2f} KES, "
                f"P99 = {stats.get('p99', 0.0):,.2f} KES"
            )
        evidence = price_analysis.get("nearest_ocids") or price_analysis.get("evidence_ocids") or []
        if evidence:
            md_lines.append(f"- **Nearest Benchmark Citations**: {', '.join(f'`{e}`' for e in evidence)}")
    else:
        md_lines.append("No price benchmark computed.")
    md_lines.append("")

    # Section 3: Supplier history
    md_lines.append("## Supplier history")
    if supplier_history:
        sup_name = supplier_history.get("supplier_name", "Unknown")
        sup_norm = supplier_history.get("supplier_name_norm", "Unknown")
        wins = supplier_history.get("total_wins", 0)
        buyers_cnt = supplier_history.get("distinct_buyers", 0)
        md_lines.append(f"- **Supplier Name**: {sup_name} (Normalized: `{sup_norm}`)")
        md_lines.append(f"- **Total Historical Wins**: {wins:,}")
        md_lines.append(f"- **Distinct Procuring Entities**: {buyers_cnt:,}")
        if supplier_history.get("concentration_flag"):
            md_lines.append(f"- **Concentration Flag**: Yes — {supplier_history.get('concentration_note', 'High buyer concentration detected')}")
        variants = supplier_history.get("merged_variants", [])
        if variants and len(variants) > 1:
            md_lines.append(f"- **Merged Name Variants**: {', '.join(f'\"{v}\"' for v in variants)}")
    else:
        md_lines.append("No supplier history provided.")
    md_lines.append("")

    # Section 4: Data-quality notes
    md_lines.append("## Data-quality notes")
    all_dq = list(data_quality_notes)
    for f in findings:
        if f.get("kind") == "data-quality":
            sources_str = ", ".join(f"`{s}`" for s in f.get("sources", []))
            all_dq.append(f"[{f.get('id', 'DQ')}] {f.get('text')} (Sources: {sources_str})")
    if all_dq:
        for dq in all_dq:
            md_lines.append(f"- {dq}")
    else:
        md_lines.append("- No data quality issues identified. Records conform to expected schema.")
    md_lines.append("")

    # Structured Findings List with citations
    md_lines.append("### Key Findings & Citations")
    for f in findings:
        sources_str = ", ".join(f"`{s}`" for s in f.get("sources", []))
        md_lines.append(
            f"- **[{f.get('id')}] [{f.get('kind').upper()}] (Severity: {f.get('severity').upper()})**: "
            f"{f.get('text')} — *Sources: {sources_str}*"
        )
    md_lines.append("")

    # Section 5: Officer decision (left blank for the gate)
    md_lines.append("## Officer decision")
    md_lines.append("*[Awaiting review by the designated procurement officer via CLI gate. Decision must be explicitly recorded before finalization.]*")
    md_lines.append("")

    draft_text = "\n".join(md_lines)

    # Double check forbidden patterns across entire output
    d_lower = draft_text.lower()
    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, d_lower):
            return {
                "valid": False,
                "errors": [f"Draft text contains forbidden recommendation language matching '{pat}'."],
                "draft": "",
            }

    return {
        "valid": True,
        "errors": [],
        "draft": draft_text,
    }


def main():
    """Run FastMCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
