"""Regression: shared message assembly matches historical NIM payload shape."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiment0.providers.base import ProviderRequest
from experiment0.providers.message_assembly import assemble_openai_chat_messages
from experiment0.providers.nim_provider import NimChatProvider


def _legacy_assemble(system: str, messages: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if system:
        out.append({"role": "system", "content": system})
    out.extend({"role": m["role"], "content": m["content"]} for m in messages)
    return out


def test_assemble_byte_for_byte_with_legacy():
    cases = [
        ("", []),
        ("sys", [{"role": "user", "content": "hi"}]),
        (
            "S",
            [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
        ),
    ]
    for system, messages in cases:
        assert assemble_openai_chat_messages(system, messages) == _legacy_assemble(
            system, messages
        )


def test_nim_build_payload_uses_shared_assembly():
    p = NimChatProvider(api_key="test-key-not-real")
    req = ProviderRequest(
        model="nvidia/nemotron-3-super-120b-a12b",
        system="sys",
        messages=[
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ],
        max_tokens=800,
        temperature=0.7,
        enable_thinking=False,
    )
    body = p._build_payload(req)
    assert body["messages"] == assemble_openai_chat_messages(req.system, req.messages)
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert body["messages"][0] == {"role": "system", "content": "sys"}
