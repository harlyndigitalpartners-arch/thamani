"""Small NVIDIA-hosted model adapter for selecting an evidence-backed review focus."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
VALID_FOCUS_AREAS = {"price", "supplier", "data-quality"}


def _api_key() -> str:
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        key_file = os.getenv("NVIDIA_API_KEY_FILE", "").strip()
        if key_file:
            key = Path(key_file).read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("NVIDIA_API_KEY or NVIDIA_API_KEY_FILE is required for a NVIDIA model run")
    return key


def select_review_focus(
    model: str,
    ocid: str,
    findings: list[dict[str, Any]],
    benchmark: dict[str, Any],
    supplier: dict[str, Any],
) -> dict[str, str]:
    """Ask the model to select a focus; accept only known areas and finding IDs.

    No generated prose is inserted into the report. Facts and citations come from
    the deterministic analysis, while the model chooses what to put first.
    """
    allowed_ids = {str(item["id"]) for item in findings if item.get("id")}
    evidence = {
        "ocid": ocid,
        "price_verdict": benchmark.get("verdict"),
        "supplier_concentration": supplier.get("concentration_flag", False),
        "findings": [
            {"id": item.get("id"), "kind": item.get("kind"), "severity": item.get("severity"),
             "text": item.get("text"), "sources": item.get("sources", [])}
            for item in findings
        ],
    }
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 120,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": (
                "You assist a Kenyan public procurement reviewer. Select one review focus from "
                "price, supplier, data-quality using only the supplied evidence. Return only JSON "
                "with keys focus_area and finding_id. finding_id must be an existing finding ID "
                "or an empty string. Do not make an award recommendation."
            )},
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
        ],
    }
    response = httpx.post(
        NVIDIA_CHAT_URL,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json=payload,
        timeout=45.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    try:
        choice = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("NVIDIA model returned invalid review-focus JSON") from exc
    focus = choice.get("focus_area")
    finding_id = choice.get("finding_id") or ""
    if focus not in VALID_FOCUS_AREAS or finding_id not in allowed_ids | {""}:
        raise ValueError("NVIDIA model returned an unsupported review focus or finding ID")
    if finding_id:
        kind = next(item.get("kind") for item in findings if item.get("id") == finding_id)
        expected_focus = {"price-outlier": "price", "concentration": "supplier", "data-quality": "data-quality"}.get(kind)
        if focus != expected_focus:
            raise ValueError("NVIDIA model focus does not match the selected finding")
    return {"focus_area": focus, "finding_id": finding_id}
