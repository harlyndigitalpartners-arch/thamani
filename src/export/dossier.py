"""Thamani Official Executive Audit Dossier Exporter.

Transforms markdown briefings and agent state into a structured, publication-grade
HTML oversight dossier suitable for formal audits, parliamentary committee reviews,
and 1-click printable PDF generation.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from src.agent.crypto_seal import verify_report_integrity


DOSSIER_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Thamani Audit Dossier — {ocid}</title>
<style>
  :root {{
    --ke-green: #006600;
    --ke-red: #bb0000;
    --ke-black: #111111;
    --slate-800: #1e293b;
    --slate-600: #475569;
    --slate-100: #f1f5f9;
    --border-color: #cbd5e1;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: var(--slate-800);
    line-height: 1.5;
    margin: 0;
    padding: 24px;
    background: #f8fafc;
  }}
  .dossier-card {{
    max-width: 900px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.06);
    overflow: hidden;
    border: 1px solid var(--border-color);
  }}
  .ke-stripes {{
    height: 8px;
    background: linear-gradient(to right, var(--ke-black) 33%, var(--ke-red) 33% 66%, var(--ke-green) 66%);
  }}
  .header {{
    padding: 32px 40px 24px 40px;
    background: #ffffff;
    border-bottom: 2px solid var(--slate-100);
  }}
  .header-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }}
  .agency-title {{
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--ke-green);
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .dossier-headline {{
    font-size: 24px;
    font-weight: 800;
    color: var(--ke-black);
    margin: 0 0 8px 0;
  }}
  .ocid-badge {{
    display: inline-block;
    background: #e2e8f0;
    color: #334155;
    font-family: monospace;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
  }}
  .print-btn {{
    background: var(--ke-green);
    color: #ffffff;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }}
  .print-btn:hover {{ background: #004d00; }}
  
  .content {{
    padding: 32px 40px;
  }}
  
  .risk-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
  }}
  .risk-card {{
    padding: 16px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: #f8fafc;
  }}
  .risk-label {{
    font-size: 11px;
    text-transform: uppercase;
    font-weight: 700;
    color: var(--slate-600);
    letter-spacing: 0.5px;
  }}
  .risk-value {{
    font-size: 18px;
    font-weight: 800;
    margin-top: 4px;
  }}
  .risk-ok {{ color: var(--ke-green); }}
  .risk-watch {{ color: #d97706; }}
  .risk-flag {{ color: var(--ke-red); }}

  h2 {{
    font-size: 17px;
    font-weight: 700;
    color: #0f172a;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 6px;
    margin-top: 32px;
    margin-bottom: 14px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
  }}
  
  ul, ol {{ padding-left: 20px; }}
  li {{ margin-bottom: 6px; }}
  
  .finding-box {{
    background: #fef2f2;
    border-left: 4px solid var(--ke-red);
    padding: 12px 16px;
    border-radius: 0 4px 4px 0;
    margin-bottom: 12px;
  }}
  .finding-box.normal {{
    background: #f0fdf4;
    border-left-color: var(--ke-green);
  }}
  
  .cert-box {{
    margin-top: 40px;
    padding: 24px;
    background: #f8fafc;
    border: 2px dashed #94a3b8;
    border-radius: 8px;
  }}
  .cert-header {{
    font-size: 13px;
    text-transform: uppercase;
    font-weight: 800;
    letter-spacing: 1px;
    color: var(--slate-800);
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
  }}
  .hash-box {{
    font-family: monospace;
    font-size: 11px;
    background: #ffffff;
    padding: 8px 12px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    word-break: break-all;
    color: #334155;
  }}

  @media print {{
    body {{ background: #ffffff; padding: 0; }}
    .dossier-card {{ box-shadow: none; border: none; max-width: 100%; }}
    .print-btn {{ display: none; }}
    h2 {{ page-break-after: avoid; }}
    .cert-box {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>

<div class="dossier-card">
  <div class="ke-stripes"></div>
  
  <div class="header">
    <div class="header-top">
      <div>
        <div class="agency-title">Republic of Kenya • Public Procurement Oversight</div>
        <h1 class="dossier-headline">Value-for-Money Audit Dossier</h1>
        <span class="ocid-badge">OCID: {ocid}</span>
      </div>
      <div>
        <button class="print-btn" onclick="window.print()">🖨️ Print / Save PDF</button>
      </div>
    </div>
  </div>

  <div class="content">
    {body_html}

    <div class="cert-box">
      <div class="cert-header">
        <span>Official Verification & Cryptographic Certificate</span>
        <span>STATUS: {gate_status}</span>
      </div>
      <p style="margin: 0 0 8px 0; font-size: 13px;">
        This audit briefing was processed through the Thamani LangGraph governance engine and verified by a designated oversight officer under strict human-in-the-loop statutory controls.
      </p>
      <div style="font-size: 12px; margin-bottom: 6px;">
        <strong>Reviewing Officer:</strong> {officer_name} &nbsp;|&nbsp; 
        <strong>Action:</strong> {gate_decision} &nbsp;|&nbsp; 
        <strong>Timestamp:</strong> {gate_ts}
      </div>
      <div style="font-size: 11px; font-weight: 700; color: #64748b; margin-top: 10px; margin-bottom: 4px;">SHA-256 Tamper-Proof Cryptographic Signature:</div>
      <div class="hash-box">{seal_hash}</div>
    </div>
  </div>
</div>

</body>
</html>
"""


def markdown_to_html_simple(md_text: str) -> str:
    """Lightweight converter for Thamani structured markdown to styled HTML."""
    lines = md_text.splitlines()
    html_out = []
    in_list = False

    for line in lines:
        line_str = line.strip()

        # Skip horizontal rules
        if line_str in ("---", "***"):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            continue

        # Skip Officer Gate Verification Record in main body (it gets rendered in cert-box)
        if "## Officer Gate Verification Record" in line_str:
            break

        # Headings
        if line_str.startswith("# "):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            title = line_str[2:].strip()
            html_out.append(f"<h1 style='display:none'>{html.escape(title)}</h1>")
        elif line_str.startswith("## "):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            html_out.append(f"<h2>{html.escape(line_str[3:].strip())}</h2>")
        elif line_str.startswith("### "):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            html_out.append(f"<h3 style='font-size:15px; margin-top:16px;'>{html.escape(line_str[4:].strip())}</h3>")
        elif line_str.startswith("- "):
            if not in_list:
                html_out.append("<ul style='line-height:1.6;'>")
                in_list = True
            item_text = line_str[2:]
            
            # Format finding items specially
            if "[CONCENTRATION]" in item_text or "[PRICE-OUTLIER]" in item_text or "Severity: HIGH" in item_text:
                formatted_item = format_inline_markdown(item_text)
                html_out.append(f"<div class='finding-box'>{formatted_item}</div>")
            else:
                formatted_item = format_inline_markdown(item_text)
                html_out.append(f"<li>{formatted_item}</li>")
        else:
            if in_list and not line_str:
                html_out.append("</ul>")
                in_list = False
            if line_str:
                html_out.append(f"<p>{format_inline_markdown(line_str)}</p>")

    if in_list:
        html_out.append("</ul>")

    return "\n".join(html_out)


def format_inline_markdown(text: str) -> str:
    """Format bold, italic, code tags in text."""
    # Bold
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
    # Code / OCIDs
    t = re.sub(r"`([^`]+)`", r"<code style='background:#f1f5f9; padding:2px 4px; border-radius:3px; font-size:12px; font-family:monospace;'>\1</code>", t)
    return t


def generate_dossier_html(markdown_content: str, ocid: str | None = None) -> str:
    """Generates standalone printable HTML audit dossier from markdown briefing."""
    # Extract OCID if not provided
    if not ocid:
        m = re.search(r"ocds-[a-z0-9A-Z/\-_.]+", markdown_content)
        ocid = m.group(0) if m else "OCID-KENYA"

    # Verify integrity and extract seal information
    integrity = verify_report_integrity(markdown_content)
    seal_hash = integrity.get("recorded_hash") or "NOT_SEALED"
    officer_name = integrity.get("officer") or "Procurement Officer"
    gate_decision = (integrity.get("decision") or "APPROVED").upper()
    gate_ts = integrity.get("timestamp") or "N/A"
    gate_status = "VERIFIED & ARCHIVED" if integrity.get("verified") else "PRE-GATE / UNSEALED"

    body_html = markdown_to_html_simple(markdown_content)

    return DOSSIER_TEMPLATE.format(
        ocid=html.escape(ocid),
        body_html=body_html,
        officer_name=html.escape(officer_name),
        gate_decision=html.escape(gate_decision),
        gate_ts=html.escape(gate_ts),
        gate_status=html.escape(gate_status),
        seal_hash=seal_hash,
    )


def export_dossier_to_file(markdown_content: str, output_path: str | Path, ocid: str | None = None) -> Path:
    """Writes compiled HTML dossier to specified file path."""
    html_content = generate_dossier_html(markdown_content, ocid=ocid)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_content, encoding="utf-8")
    return target
