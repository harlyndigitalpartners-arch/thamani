"""Read-only integration checks against the bundled procurement snapshot."""
from pathlib import Path

import pytest

from src.agent.loop import run_pipeline
from src.thamani_server import server


DB = Path(__file__).resolve().parents[1] / "data/thamani.sqlite"


@pytest.mark.skipif(not DB.is_file(), reason="Extract or rebuild the bundled database first")
@pytest.mark.parametrize("ocid", ["ocds-5whusi-PCKTTI-2695", "ocds-5whusi-1033", "ocds-5whusi-275077-PBSS/2025/2026/001"])
def test_demo_cases_stop_at_pending_human_gate(tmp_path, monkeypatch, ocid):
    monkeypatch.setattr(server, "DEFAULT_DB_PATH", DB)
    monkeypatch.chdir(tmp_path)
    result = run_pipeline(ocid, officer="Officer A", interactive=False)
    assert not result.get("error")
    assert result["draft"]
    assert result["gate_decision"]["decision"] == "pending"
    assert not result.get("final_report_path")
    logs = list((tmp_path / "runs").glob("*.jsonl"))
    assert len(logs) == 1
    assert len(logs[0].read_text().splitlines()) == len(result["run_log"])
    if ocid.endswith("PCKTTI-2695"):
        amark = next(item for item in result["all_suppliers"] if item["supplier_name_norm"] == "AMARK NORTHERN AGENCY")
        assert amark["total_wins"] == 195
