"""Thamani report integrity checksum and verification.

Enforces governance integrity by computing SHA-256 cryptographic fingerprints
for finalized value-for-money briefings. Any modification to an archived report
invalidates the checksum. This is not an identity signature: a party able to
replace both the report and checksum can recompute it.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


def compute_seal_hash(content: str, officer_name: str, timestamp: str, decision: str) -> str:
    """Generate deterministic SHA-256 hex digest for finalized audit content."""
    payload = f"OFFICER:{officer_name.strip()}|DECISION:{decision.strip().upper()}|TS:{timestamp.strip()}|CONTENT:{content.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_gate_record_with_seal(
    content_to_seal: str,
    officer_name: str,
    decision_type: str,
    timestamp: str,
    override_id: str | None = None,
    note: str | None = None,
) -> tuple[str, str]:
    """Builds formatted gate verification block with embedded SHA-256 cryptographic seal.

    Returns:
        tuple[str, str]: (gate_record_markdown, sha256_hash)
    """
    lines = [
        "",
        "---",
        "## Officer Gate Verification Record",
        "- **Seal Version**: `2`",
        f"- **Reviewing Officer**: {officer_name}",
        f"- **Verification Decision**: `{decision_type.upper()}`",
        f"- **Timestamp**: `{timestamp}`",
    ]

    if decision_type.lower() == "override":
        lines.append(f"- **Officer Override Finding Target**: `{override_id or 'finding-1'}`")
        lines.append(f"- **Officer Formal Determination**: {note or 'Officer override entered.'}")
    else:
        lines.append(f"- **Officer Remarks**: {note or 'Approved as drafted by reviewing officer.'}")

    lines.extend(["- **Audit Status**: VERIFIED CHECKSUM; RETAIN ORIGINAL FOR ARCHIVAL", "---"])
    # Cover the complete record, including remarks, override ID and trailing text.
    unsigned_report = content_to_seal.strip() + "\n" + "\n".join(lines).strip()
    seal_hash = compute_seal_hash(unsigned_report, officer_name, timestamp, decision_type)
    lines.insert(-2, f"- **Report Integrity Checksum (SHA-256)**: `{seal_hash}`")

    return "\n".join(lines), seal_hash


def verify_report_integrity(report_path_or_content: str | Path) -> dict[str, Any]:
    """Verifies that an archived briefing file has not been altered since signing.

    Returns:
        dict containing verified (bool), expected_hash, actual_hash, and metadata.
    """
    if isinstance(report_path_or_content, Path) or (
        isinstance(report_path_or_content, str) and "\n" not in report_path_or_content and Path(report_path_or_content).exists()
    ):
        raw_text = Path(report_path_or_content).read_text(encoding="utf-8")
    else:
        raw_text = str(report_path_or_content)

    # Extract Gate Verification section
    seal_match = re.search(
        r"## Officer Gate Verification Record\s*\n"
        r"(?:- \*\*Seal Version\*\*:\s*`2`\s*\n)?"
        r"- \*\*Reviewing Officer\*\*:\s*(?P<officer>[^\n]+)\s*\n"
        r"- \*\*Verification Decision\*\*:\s*`(?P<decision>[^\n`]+)`\s*\n"
        r"- \*\*Timestamp\*\*:\s*`(?P<ts>[^\n`]+)`.*?"
        r"- \*\*(?:Report Integrity Checksum|Cryptographic Tamper-Proof Seal) \(SHA-256\)\*\*:\s*`(?P<hash>[a-f0-9]{64})`",
        raw_text,
        re.DOTALL,
    )

    if not seal_match:
        return {
            "verified": False,
            "error": "No valid cryptographic seal block found in document.",
        }

    officer = seal_match.group("officer").strip()
    decision = seal_match.group("decision").strip()
    ts = seal_match.group("ts").strip()
    recorded_hash = seal_match.group("hash").strip()

    version = 2 if "- **Seal Version**: `2`" in seal_match.group(0) else 1
    if version == 2:
        # Exactly one verification record and checksum must exist.
        if raw_text.count("## Officer Gate Verification Record") != 1:
            return {"verified": False, "error": "Multiple verification records found."}
        unsigned, count = re.subn(
            r"^- \*\*Report Integrity Checksum \(SHA-256\)\*\*: `([a-f0-9]{64})`\r?\n",
            "", raw_text, flags=re.MULTILINE,
        )
        if count != 1:
            return {"verified": False, "error": "Expected one report checksum."}
        # Generation joins the stripped draft and stripped record with one newline.
        unsigned = unsigned.replace("\r\n", "\n")
        prefix, suffix = unsigned.split("## Officer Gate Verification Record", 1)
        prefix = re.sub(r"\n---\s*$", "", prefix).strip()
        canonical = prefix + "\n---\n## Officer Gate Verification Record" + suffix
        expected_hash = compute_seal_hash(canonical.strip(), officer, ts, decision)
    else:
        pre_seal_split = raw_text.split("## Officer Gate Verification Record")[0]
        pre_seal_content = re.sub(r"\n---\s*$", "", pre_seal_split).strip()
        expected_hash = compute_seal_hash(pre_seal_content, officer, ts, decision)
    is_valid = (expected_hash == recorded_hash)

    return {
        "verified": is_valid,
        "recorded_hash": recorded_hash,
        "expected_hash": expected_hash,
        "officer": officer,
        "decision": decision,
        "timestamp": ts,
        "seal_version": version,
        "metadata_protected": version == 2,
    }
