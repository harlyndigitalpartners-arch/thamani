"""Tests for Thamani Cryptographic Tamper-Proof Seal."""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.agent.crypto_seal import (
    compute_seal_hash,
    generate_gate_record_with_seal,
    verify_report_integrity,
)


def test_crypto_seal_generation_and_verification():
    content = "# Value-for-Money Analysis Briefing: ocds-test-123\n\nSome findings."
    officer = "Jane Doe"
    decision = "approve"
    ts = "2026-10-08T00:00:00Z"

    record_str, seal_hash = generate_gate_record_with_seal(
        content_to_seal=content,
        officer_name=officer,
        decision_type=decision,
        timestamp=ts,
    )

    full_report = content + "\n" + record_str

    # Verification must succeed
    res = verify_report_integrity(full_report)
    assert res["verified"] is True
    assert res["recorded_hash"] == seal_hash
    assert res["officer"] == officer


def test_crypto_seal_catches_tampering():
    content = "# Value-for-Money Analysis Briefing: ocds-test-123\n\nOriginal finding."
    officer = "Jane Doe"
    decision = "approve"
    ts = "2026-10-08T00:00:00Z"

    record_str, seal_hash = generate_gate_record_with_seal(
        content_to_seal=content,
        officer_name=officer,
        decision_type=decision,
        timestamp=ts,
    )

    full_report = content + "\n" + record_str

    # Tamper with the content
    tampered_report = full_report.replace("Original finding.", "TAMPERED MODIFIED finding.")

    res = verify_report_integrity(tampered_report)
    assert res["verified"] is False
    assert res["expected_hash"] != res["recorded_hash"]
