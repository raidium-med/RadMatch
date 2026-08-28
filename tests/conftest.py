"""Shared pytest fixtures."""

from __future__ import annotations

import json

import pytest

from tests.fakes.fake_llm_client import FakeLLMClient


@pytest.fixture
def fake_client():
    """Factory for FakeLLMClient. Call with a list of scripted responses.

    Each item is either a JSON string (LLM reply) or an Exception (raised).
    """

    def _make(*responses) -> FakeLLMClient:
        return FakeLLMClient(script=list(responses))

    return _make


@pytest.fixture
def ok():
    """Serialize a dict as a JSON string — the canonical LLM-reply format."""
    return lambda payload: json.dumps(payload)


@pytest.fixture
def make_finding():
    """Build a finding dict with sensible defaults; pass overrides as kwargs."""

    def _make(fid: str, **overrides) -> dict:
        base: dict[str, object] = {
            "finding_id": fid,
            "text": "x",
            "clinical_status": "abnormal",
            "clinical_significance": "notable",
            "comparison": None,
            "measurements": [],
        }
        base.update(overrides)
        return base

    return _make
