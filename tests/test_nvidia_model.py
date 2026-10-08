"""Model boundary: accept only a review focus backed by computed findings."""

from __future__ import annotations

import json

import pytest

from src.agent import nvidia_model


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


def test_nvidia_review_focus_uses_secret_file_and_validates_choice(tmp_path, monkeypatch):
    secret = tmp_path / "nvidia.txt"
    secret.write_text("nvapi-test-key", encoding="utf-8")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY_FILE", str(secret))
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse('{"focus_area":"supplier","finding_id":"SC-1"}')

    monkeypatch.setattr(nvidia_model.httpx, "post", fake_post)
    findings = [{"id": "SC-1", "kind": "concentration", "severity": "high",
                 "text": "Ten historical wins from one buyer.", "sources": ["ocds-test-1"]}]
    choice = nvidia_model.select_review_focus(nvidia_model.DEFAULT_NVIDIA_MODEL, "ocds-test-1", findings, {}, {})
    assert choice == {"focus_area": "supplier", "finding_id": "SC-1"}
    assert calls[0][1]["Authorization"] == "Bearer nvapi-test-key"
    assert json.loads(calls[0][2]["messages"][1]["content"])["findings"] == findings

    monkeypatch.setattr(nvidia_model.httpx, "post", lambda *args, **kwargs: FakeResponse(
        '{"focus_area":"supplier","finding_id":"invented"}'
    ))
    with pytest.raises(ValueError, match="unsupported review focus"):
        nvidia_model.select_review_focus(nvidia_model.DEFAULT_NVIDIA_MODEL, "ocds-test-1", findings, {}, {})

    monkeypatch.setattr(nvidia_model.httpx, "post", lambda *args, **kwargs: FakeResponse(
        '{"focus_area":"price","finding_id":"SC-1"}'
    ))
    with pytest.raises(ValueError, match="does not match"):
        nvidia_model.select_review_focus(nvidia_model.DEFAULT_NVIDIA_MODEL, "ocds-test-1", findings, {}, {})
