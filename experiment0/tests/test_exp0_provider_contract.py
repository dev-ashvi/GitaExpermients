"""Provider normalized contract unit tests (no live API)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiment0.providers.base import ProviderRequest
from experiment0.providers.nim_provider import NimChatProvider, _extract_assistant_text


def test_extract_assistant_text():
    payload = {
        "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}]
    }
    assert _extract_assistant_text(payload) == '{"ok": true}'


def test_nim_payload_omits_top_p_and_seed_and_sets_thinking_false():
    p = NimChatProvider(api_key="test-key-not-real")
    req = ProviderRequest(
        model="nvidia/nemotron-3-super-120b-a12b",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=16,
        temperature=0.7,
        enable_thinking=False,
    )
    body = p._build_payload(req)
    assert "top_p" not in body
    assert "seed" not in body
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert body["temperature"] == 0.7
    assert body["messages"][0] == {"role": "system", "content": "sys"}


def test_nim_normalize_usage_fields():
    p = NimChatProvider(api_key="test-key-not-real")
    parsed = {
        "id": "chatcmpl-x",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hello"},
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
        },
    }
    norm = p._normalize(parsed, latency_ms=12, retries=0)
    assert norm.text == "hello"
    assert norm.prompt_tokens == 10
    assert norm.completion_tokens == 2
    assert norm.total_tokens == 12
    assert norm.finish_reason == "stop"
    assert norm.model_id_returned == "nvidia/nemotron-3-super-120b-a12b"
    assert norm.ok
