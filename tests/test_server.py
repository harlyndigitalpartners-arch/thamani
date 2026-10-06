"""Unit tests for Thamani FastMCP tools and verdict boundaries."""

from __future__ import annotations

import pytest
from src.thamani_server.ocds import norm_name
from src.thamani_server.server import (
    briefing_draft,
    ocds_fetch,
    price_benchmark,
    validate_findings,
)

DB_PATH = "data/thamani.sqlite"


def test_norm_name_variants():
    # Specification test: AFRICAN TOUCH SAFARIS / AFRICAN TOUCH SAFARIS LIMITED -> same supplier
    ats1 = norm_name("AFRICAN TOUCH SAFARIS")
    ats2 = norm_name("AFRICAN TOUCH SAFARIS LIMITED")
    ats3 = norm_name("African Touch Safaris Ltd.")
    ats4 = norm_name("AFRICAN TOUCH SAFARIS CO. LTD")
    assert ats1 == "AFRICAN TOUCH SAFARIS"
    assert ats2 == "AFRICAN TOUCH SAFARIS"
    assert ats3 == "AFRICAN TOUCH SAFARIS"
    assert ats4 == "AFRICAN TOUCH SAFARIS"

    # AMARK NORTHERN AGENCY
    amark = norm_name("AMARK NORTHERN AGENCY LIMITED")
    assert amark == "AMARK NORTHERN AGENCY"


def test_ocds_fetch_known_and_unknown():
    # Unknown OCID must raise clear ValueError
    with pytest.raises(ValueError, match="Unknown OCID"):
        ocds_fetch("nonexistent-ocid-12345", db_path=DB_PATH)

    # Test with AMARK award OCID
    res = ocds_fetch("ocds-5whusi-PCKTTI-2695", db_path=DB_PATH)
    assert res["ocid"] == "ocds-5whusi-PCKTTI-2695"
    assert "tender" in res
    assert len(res["awards"]) > 0
    amark_awards = [a for a in res["awards"] if a["supplier_name_norm"] == "AMARK NORTHERN AGENCY"]
    assert len(amark_awards) > 0
    assert amark_awards[0]["source_ref"] == "ocds-5whusi-PCKTTI-2695"


def test_price_benchmark_verdicts():
    # 1. Works award of 500M KES -> flag (acceptance test from §4.2)
    flag_res = price_benchmark("works", 500_000_000.0, "KES", db_path=DB_PATH)
    assert flag_res["verdict"] == "flag"
    assert len(flag_res["nearest_ocids"]) == 5
    assert flag_res["stats"]["median"] > 0

    # 2. Works award of 2.5M KES -> ok (acceptance test from §4.2)
    ok_res = price_benchmark("works", 2_500_000.0, "KES", db_path=DB_PATH)
    assert ok_res["verdict"] == "ok"
    assert len(ok_res["nearest_ocids"]) == 5

    # 3. Watch boundary (> 1.5 * median, but < 3 * median and < p99)
    # median works is ~2.5M, so 1.8 * median is ~4.5M -> watch
    med = ok_res["stats"]["median"]
    watch_val = med * 1.8
    watch_res = price_benchmark("works", watch_val, "KES", db_path=DB_PATH)
    assert watch_res["verdict"] == "watch"

    # 4. Non-positive value -> data-quality (§4.2)
    zero_res = price_benchmark("works", 0.0, "KES", db_path=DB_PATH)
    assert zero_res["verdict"] == "data-quality"
    assert "non-positive" in zero_res["note"]

    neg_res = price_benchmark("works", -100.0, "KES", db_path=DB_PATH)
    assert neg_res["verdict"] == "data-quality"

    # 5. Currency != KES -> data-quality (§4.2)
    usd_res = price_benchmark("works", 25_000.0, "USD", db_path=DB_PATH)
    assert usd_res["verdict"] == "data-quality"
    assert "USD" in usd_res["note"]

    # 6. Absurd value (> 1000 * median) -> data-quality (EVALS Task 6)
    absurd_val = med * 1500
    absurd_res = price_benchmark("works", absurd_val, "KES", db_path=DB_PATH)
    assert absurd_res["verdict"] == "data-quality"
    assert "absurd value" in absurd_res["note"]


def test_briefing_draft_validation_gate():
    # Missing sources must reject
    invalid_finding_no_source = [
        {
            "id": "F-01",
            "kind": "price-outlier",
            "severity": "high",
            "text": "Outlier price detected.",
            "sources": [],  # Empty!
        }
    ]
    res1 = briefing_draft(invalid_finding_no_source)
    assert not res1["valid"]
    assert any("missing source citations" in err for err in res1["errors"])

    # Missing text must reject
    invalid_finding_no_text = [
        {
            "id": "F-02",
            "kind": "concentration",
            "severity": "medium",
            "text": "",  # Empty!
            "sources": ["ocds-sample-1"],
        }
    ]
    res2 = briefing_draft(invalid_finding_no_text)
    assert not res2["valid"]
    assert any("missing or empty text" in err for err in res2["errors"])

    # Forbidden recommendation language must reject
    forbidden_finding = [
        {
            "id": "F-03",
            "kind": "data-quality",
            "severity": "low",
            "text": "We recommend awarding the tender to this entity.",
            "sources": ["ocds-sample-1"],
        }
    ]
    res3 = briefing_draft(forbidden_finding)
    assert not res3["valid"]
    assert any("forbidden outcome/recommendation" in err for err in res3["errors"])

    # Valid finding generates valid draft with all 5 sections
    valid_findings = [
        {
            "id": "F-01",
            "kind": "price-outlier",
            "severity": "high",
            "text": "Award value exceeds category P99 threshold.",
            "sources": ["ocds-test-1", "ocds-test-2"],
        }
    ]
    res4 = briefing_draft(
        findings=valid_findings,
        tender_summary={"ocid": "ocds-test-1", "title": "Test Tender", "category": "works"},
    )
    assert res4["valid"]
    draft = res4["draft"]
    assert "## Award summary" in draft
    assert "## Price analysis" in draft
    assert "## Supplier history" in draft
    assert "## Data-quality notes" in draft
    assert "## Officer decision" in draft
    assert "[Awaiting review by the designated procurement officer" in draft
