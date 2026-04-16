"""
Regression test for PR #1099: Ollama native API must include think=False.

Without this flag, reasoning models (qwen3.5, deepseek-r1, etc.) route their
entire response to the thinking field, leaving message.content empty and
breaking structured output (fact extraction, consolidation, etc.).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

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


def _build_mock_client(captured_payloads: list[dict]) -> MagicMock:
    """Build a mock httpx.AsyncClient that captures post payloads."""
    mock_post = AsyncMock(side_effect=lambda url, **kw: (
        captured_payloads.append(kw.get("json")),
        _mock_ollama_response({"summary": "test"}),
    )[-1])

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
@pytest.mark.parametrize("response_format", [_SampleOutput, None])
async def test_ollama_native_payload_includes_think_false(response_format):
    """think=False must be in every _call_ollama_native payload (PR #1099)."""
    llm = _make_ollama_llm()
    captured_payloads: list[dict] = []
    mock_client = _build_mock_client(captured_payloads)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await llm._call_ollama_native(
            messages=[{"role": "user", "content": "hello"}],
            response_format=response_format,
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
async def test_ollama_native_think_false_coexists_with_schema_and_options():
    """think=False must coexist with format, num_predict, and temperature."""
    llm = _make_ollama_llm()
    captured_payloads: list[dict] = []
    mock_client = _build_mock_client(captured_payloads)

    with patch("httpx.AsyncClient", return_value=mock_client):
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

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload["think"] is False
    assert "format" in payload, "schema must be passed as 'format'"
    assert payload["options"]["num_predict"] == 512
    assert payload["options"]["temperature"] == 0.1
