"""Pure OpenAI chat-message assembly shared by NIM provider and local token counter.

Must stay byte-for-byte equivalent to historical NimChatProvider message list
construction (system prepend + role/content copies).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


def assemble_openai_chat_messages(
    system: str,
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Build the OpenAI-shaped messages array sent to NIM chat completions.

    Equivalent to the message-list portion of NimChatProvider._build_payload:
    - If system is non-empty, prepend {role: system, content: system}
    - Append each history message with role/content string fields only
    """
    out: list[dict[str, str]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        out.append({"role": str(m["role"]), "content": str(m["content"])})
    return out


def openai_chat_request_body(
    *,
    model: str,
    system: str,
    messages: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float,
    enable_thinking: bool,
) -> dict[str, Any]:
    """Provider-facing JSON body fields relevant to tokenization / qualification."""
    return {
        "model": model,
        "messages": assemble_openai_chat_messages(system, messages),
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "chat_template_kwargs": {"enable_thinking": bool(enable_thinking)},
    }
