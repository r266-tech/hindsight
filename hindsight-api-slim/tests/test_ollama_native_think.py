"""
Regression test for PR #1099: Ollama native API must include think=False.

Without this flag, reasoning models (qwen3.5, deepseek-r1, etc.) route their
entire response to the thinking field, leaving message.content empty and
breaking structured output (fact extraction, consolidation, etc.).
"""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import BaseModel

from hindsight_api.engine.providers.openai_compatible_llm import OpenAICompatibleLLM


class _SampleOutput(BaseModel):
    summary: str


def _make_ollama_llm(**overrides) -> OpenAICompatibleLLM:
    defaults = dict(
        provider="ollama",
        api_key="",
        base_url="http://localhost:11434/v1",
        model="qwen3.5:2b",
    )
    defaults.update(overrides)
    return OpenAICompatibleLLM(**defaults)


def _mock_ollama_response(content: dict) -> httpx.Response:
    body = {
        "model": "qwen3.5:2b",
        "message": {"role": "assistant", "content": json.dumps(content)},
        "done": True,
    }
    return httpx.Response(200, json=body)


@pytest.mark.asyncio
async def test_ollama_native_payload_includes_think_false():
    """think=False must be in every _call_ollama_native payload (PR #1099)."""
    llm = _make_ollama_llm()
    captured_payloads: list[dict] = []

    async def _capture_post(url, *, json=None, **kw):
        captured_payloads.append(json)
        return _mock_ollama_response({"summary": "test"})

    with patch("httpx.AsyncClient.post", new_callable=lambda: lambda: AsyncMock(side_effect=_capture_post)):
        await llm._call_ollama_native(
            messages=[{"role": "user", "content": "hello"}],
            response_format=_SampleOutput,
            max_completion_tokens=None,
            temperature=None,
            max_retries=0,
            initial_backoff=1.0,
            max_backoff=10.0,
            skip_validation=True,
        )

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert "think" in payload, "payload must include 'think' key"
    assert payload["think"] is False, "think must be False to prevent reasoning models routing output to thinking field"


@pytest.mark.asyncio
async def test_ollama_native_think_false_coexists_with_schema():
    """think=False must be present alongside the format (schema) parameter."""
    llm = _make_ollama_llm()
    captured_payloads: list[dict] = []

    async def _capture_post(url, *, json=None, **kw):
        captured_payloads.append(json)
        return _mock_ollama_response({"summary": "test"})

    with patch("httpx.AsyncClient.post", new_callable=lambda: lambda: AsyncMock(side_effect=_capture_post)):
        await llm._call_ollama_native(
            messages=[{"role": "user", "content": "extract facts"}],
            response_format=_SampleOutput,
            max_completion_tokens=512,
            temperature=0.1,
            max_retries=0,
            initial_backoff=1.0,
            max_backoff=10.0,
            skip_validation=True,
        )

    payload = captured_payloads[0]
    assert payload["think"] is False
    assert "format" in payload, "schema must be passed as 'format'"
    assert payload["options"]["num_predict"] == 512
    assert payload["options"]["temperature"] == 0.1
