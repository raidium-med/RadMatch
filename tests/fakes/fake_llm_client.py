"""A deterministic fake `Client` for unit tests.

Behaviour is driven by a script: a list of response strings or
exceptions, consumed in order on each call to `complete()`. Useful for
exercising validation-retry and transient-error retry paths without
hitting a live LLM.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from radmatch.llm_utils import llm_clients


class FakeLLMClient(llm_clients.Client):
    """Client stub. Returns scripted responses, records calls."""

    def __init__(
        self,
        script: Sequence[object] | None = None,
        max_tokens: int = 1024,
        reasoning: str = "none",
    ):
        # Bypass parent __init__ which would set model — not relevant for a fake.
        self.model = "fake"
        self.max_tokens = max_tokens
        self.reasoning = reasoning
        self.script: list[object] = list(script or [])
        self.calls: list[dict] = []  # records (messages, response_format, max_tokens) per call

    def push(self, *items: object) -> "FakeLLMClient":
        """Append items to the script. Returns self for chaining."""
        self.script.extend(items)
        return self

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        response_format: Mapping[str, object] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(
            {
                "messages": list(messages),
                "response_format": response_format,
                "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            }
        )
        if not self.script:
            raise AssertionError("FakeLLMClient script exhausted; provide more responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return item
        raise AssertionError(f"FakeLLMClient script item must be Exception or str, got {type(item).__name__}")
