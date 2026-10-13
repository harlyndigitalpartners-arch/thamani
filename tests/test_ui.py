"""Exercise officer review through Streamlit, including missing price statistics."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.agent import loop
from tests.test_regressions import pending_state


def dashboard(tmp_path, monkeypatch):
    entry = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    monkeypatch.chdir(tmp_path)

    def preview(ocid, **kwargs):
        state = pending_state()
        state.update(ocid=ocid, tender={"ocid": ocid, "title": "Test record", "category": "goods", "buyer_name": "Buyer"},
                     awards=[{"award_id": "A1", "value_amount": 0, "value_currency": "KES"}],
                     benchmarks=[{"verdict": "data-quality", "stats": None, "note": "non-positive award value"}])
        return state

    monkeypatch.setattr(loop, "run_pipeline", preview)

    def write_file(self, filename, content):
        target = self.root_dir / filename
        target.write_text(content, encoding="utf-8")
        return target
    monkeypatch.setattr(loop.FilesystemMCPClient, "write_file", write_file)
    app = AppTest.from_file(str(entry), default_timeout=30).run()
    assert not app.exception
    next(button for button in app.button if "Run Agentic Audit" in button.label).click().run()
    return app


def test_data_quality_preview_and_rejection(tmp_path, monkeypatch):
    app = dashboard(tmp_path, monkeypatch)
    assert not app.exception
    next(field for field in app.text_input if field.label == "Designated Officer Name").set_value("Officer A").run()
    next(radio for radio in app.radio if radio.label == "Officer Verification Decision").set_value("Reject Briefing").run()
    next(button for button in app.button if "Formally Sign" in button.label).click().run()
    assert not app.exception
    assert not list((tmp_path / "reports").glob("*.md"))
    assert not app.get("download_button")


def test_missing_reviewer_name_explains_disabled_signing(tmp_path, monkeypatch):
    app = dashboard(tmp_path, monkeypatch)
    assert next(button for button in app.button if "Formally Sign" in button.label).disabled
    assert any("Designated Officer Name" in warning.value for warning in app.warning)
    next(field for field in app.text_input if field.label == "Designated Officer Name").set_value("Officer A").run()
    assert not next(button for button in app.button if "Formally Sign" in button.label).disabled


def test_approval_exposes_downloads_and_disables_repeat_review(tmp_path, monkeypatch):
    app = dashboard(tmp_path, monkeypatch)
    next(field for field in app.text_input if field.label == "Designated Officer Name").set_value("Officer A").run()
    next(button for button in app.button if "Formally Sign" in button.label).click().run()
    assert not app.exception
    assert len(app.get("download_button")) == 2
    assert next(button for button in app.button if "Formally Sign" in button.label).disabled
    assert any("already been reviewed" in message.value for message in app.info)
    assert len(list((tmp_path / "reports").glob("*.md"))) == 1
    # A document frame isolates the printable page from the dashboard's styles
    # and preserves the trusted template's Print button handler.
    frames = app.get("iframe")
    assert len(frames) == 1
    assert "window.print()" in frames[0].proto.srcdoc
    assert "Officer A" in frames[0].proto.srcdoc
