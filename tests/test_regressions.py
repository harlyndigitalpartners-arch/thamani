"""Regression checks for data, review, and exported-report boundaries."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from src.agent import loop
from src.agent.crypto_seal import generate_gate_record_with_seal, verify_report_integrity
from src.export.dossier import format_inline_markdown, generate_dossier_html
from src.thamani_server.ocds import ingest_file, init_db
from src.thamani_server.server import price_benchmark


def release(amount=100, currency="KES", suppliers=None):
    return {"ocid": "ocds-test-1", "tender": {"mainProcurementCategory": "goods"},
            "awards": [{"id": "A1", "value": {"amount": amount, "currency": currency},
                        "suppliers": suppliers or [{"id": "S1", "name": "Supplier"}]}]}


def ingest(tmp_path, records, name="test"):
    archive = tmp_path / f"{name}.jsonl.gz"
    with gzip.open(archive, "wt", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    db = tmp_path / f"{name}.sqlite"
    conn = init_db(db)
    ingest_file(archive, conn)
    return db, archive, conn


def test_reingestion_updates_without_duplicate_awards(tmp_path):
    db, archive, conn = ingest(tmp_path, [release()])
    try:
        ingest_file(archive, conn)
        assert conn.execute("SELECT count(*) FROM awards").fetchone()[0] == 1
        with gzip.open(archive, "wt", encoding="utf-8") as f:
            f.write(json.dumps(release(200)) + "\n")
        ingest_file(archive, conn)
        assert conn.execute("SELECT value_amount FROM awards").fetchall() == [(200.0,)]
    finally:
        conn.close()


def test_benchmarks_follow_database_and_updates(tmp_path):
    for name, amount in [("first", 100), ("second", 900)]:
        db, _, conn = ingest(tmp_path, [release(amount)], name)
        try:
            assert price_benchmark("goods", amount, db_path=str(db))["stats"]["median"] == amount
            conn.execute("UPDATE awards SET value_amount = ?", (amount * 2,))
            conn.commit()
            assert price_benchmark("goods", amount, db_path=str(db))["stats"]["median"] == amount * 2
        finally:
            conn.close()


def test_joint_supplier_award_is_one_benchmark_and_currency_is_filtered(tmp_path):
    joint = release(suppliers=[{"id": "S1", "name": "One"}, {"id": "S2", "name": "Two"}])
    foreign = release(10000, "USD")
    foreign["ocid"] = "ocds-test-foreign"
    db, _, conn = ingest(tmp_path, [joint, foreign])
    conn.close()
    result = price_benchmark("goods", 100, db_path=str(db))
    assert result["stats"]["n"] == 1
    assert result["stats"]["median"] == 100
    assert len(result["nearest_awards"]) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_price_is_data_quality(value):
    assert price_benchmark("goods", value)["verdict"] == "data-quality"


@pytest.mark.parametrize("old,new", [("Original note", "Edited note"), ("F-1", "F-2"),
                                    ("VERIFIED", "INVALID")])
def test_seal_protects_entire_gate_record(old, new):
    content = "# Briefing\nOriginal findings."
    record, _ = generate_gate_record_with_seal(content, "Officer A", "override", "2026-10-13", "F-1", "Original note")
    report = content + "\n" + record
    assert verify_report_integrity(report)["verified"]
    assert not verify_report_integrity(report.replace(old, new))["verified"]
    assert not verify_report_integrity(report + "\nAdded after sealing")["verified"]


def test_dossier_cannot_force_invalid_content_to_verified():
    assert "STATUS: VERIFIED" not in generate_dossier_html("# Unsealed draft", is_sealed=True)


def test_dossier_escapes_source_html():
    rendered = format_inline_markdown('<script>alert(1)</script> **Safe bold**')
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<strong>Safe bold</strong>" in rendered


def pending_state():
    return {"ocid": "ocds-test-1", "officer": "Officer A", "draft": "# Draft\n## Officer decision\n*[Awaiting review by the designated procurement officer via CLI gate. Decision must be explicitly recorded before finalization.]*",
            "findings": [{"id": "F-1", "kind": "data-quality", "severity": "low", "text": "Check record", "sources": ["ocds-test-1"]}],
            "gate_decision": {"decision": "pending"}, "run_log": []}


@pytest.mark.parametrize("action", ["override missing A note", "override F-1", "override F-1   "])
def test_gate_refuses_invalid_overrides(action):
    state = pending_state() | {"auto_gate_action": action}
    with pytest.raises(ValueError):
        loop.gate_node(state)


def test_review_requires_named_officer():
    with pytest.raises(ValueError):
        loop.finalize_reviewed_state(pending_state(), "   ", "approve")


def test_report_and_log_versions_are_preserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Isolate persistence from the external server; its real integration is checked separately.
    def write_file(self, filename, content):
        target = self.root_dir / filename
        target.write_text(content, encoding="utf-8")
        return target
    monkeypatch.setattr(loop.FilesystemMCPClient, "write_file", write_file)
    first = loop.finalize_reviewed_state(pending_state(), "Officer A", "approve")
    first_content = Path(first["final_report_path"]).read_text(encoding="utf-8")
    second = loop.finalize_reviewed_state(pending_state(), "Officer B", "override F-1 A justified correction")
    assert first["final_report_path"] != second["final_report_path"]
    assert Path(first["final_report_path"]).read_text(encoding="utf-8") == first_content
    assert verify_report_integrity(Path(second["final_report_path"]))["verified"]
    assert loop.persist_run_log([]) != loop.persist_run_log([])


def test_failed_report_write_preserves_officer_decision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    def fail_write(*args):
        raise OSError("Server unavailable")
    monkeypatch.setattr(loop.FilesystemMCPClient, "write_file", fail_write)
    with pytest.raises(OSError):
        loop.finalize_reviewed_state(pending_state(), "Officer A", "approve")
    logs = list((tmp_path / "runs").glob("*.jsonl"))
    entries = [json.loads(line) for path in logs for line in path.read_text().splitlines()]
    assert any(entry["node"] == "gate" and entry["outputs_summary"]["decision"] == "approve" for entry in entries)
    assert not list((tmp_path / "reports").glob("*.md"))


def test_failed_pipeline_keeps_completed_node_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    class FailingGraph:
        def stream(self, *args, **kwargs):
            yield {"plan": {"run_log": [{"node": "plan", "outputs_summary": {"steps_count": 6}}]}}
            raise RuntimeError("Later node failed")
    monkeypatch.setattr(loop, "build_thamani_graph", lambda: FailingGraph())
    with pytest.raises(RuntimeError):
        loop.run_pipeline("ocds-test-1", interactive=False)
    logs = list((tmp_path / "runs").glob("*.jsonl"))
    assert json.loads(logs[0].read_text().splitlines()[0])["node"] == "plan"


def test_demo_requires_interactive_review(monkeypatch):
    calls = []
    monkeypatch.setattr(loop, "run_pipeline", lambda **kwargs: calls.append(kwargs) or {})
    loop.run_demo("Officer A")
    assert len(calls) == 3
    assert all(call["interactive"] and not call.get("auto_gate_action") for call in calls)


def test_legacy_duplicate_cache_migrates_to_latest_row(tmp_path):
    db, _, conn = ingest(tmp_path, [release()])
    conn.execute("DROP INDEX idx_awards_identity")
    conn.execute("""INSERT INTO awards(ocid, award_id, value_amount, supplier_name_norm)
                    VALUES ('ocds-test-1', 'A1', 200, 'SUPPLIER')""")
    conn.commit()
    conn.close()
    conn = init_db(db)
    assert conn.execute("SELECT value_amount FROM awards").fetchall() == [(200.0,)]
    conn.close()
