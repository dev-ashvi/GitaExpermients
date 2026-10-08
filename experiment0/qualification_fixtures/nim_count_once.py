"""Single-shot NVIDIA NIM prompt-token probe (no retries, no Actor/Witness loops).

Engineering qualification only. Does not print API keys.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


class NimProbeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        raw: Any = None,
        rate_limited: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw
        self.rate_limited = rate_limited


def post_chat_completions_once(
    *,
    base_url: str,
    api_key: str,
    body: dict[str, Any],
    timeout_sec: float = 600.0,
) -> dict[str, Any]:
    """Exactly one HTTP POST. No nested retries. No 429 retry."""
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
        status = int(e.code)
        if status == 429:
            raise NimProbeError(
                f"HTTP 429 rate limited: {raw[:400]}",
                status_code=429,
                raw=raw[:2000],
                rate_limited=True,
            )
        raise NimProbeError(
            f"HTTP {status}: {raw[:500]}",
            status_code=status,
            raw=raw[:2000],
        )
    except Exception as e:  # noqa: BLE001
        raise NimProbeError(f"Transport failure (no retry): {e}") from e

    if status != 200:
        if status == 429:
            raise NimProbeError(
                f"HTTP 429: {raw[:400]}",
                status_code=429,
                raw=raw[:2000],
                rate_limited=True,
            )
        raise NimProbeError(
            f"HTTP {status}: {raw[:500]}",
            status_code=status,
            raw=raw[:2000],
        )
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise NimProbeError(f"Non-JSON response: {e}", status_code=status, raw=raw[:1000]) from e
    return parsed


def extract_prompt_tokens(parsed: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    usage = parsed.get("usage") or {}
    pt = usage.get("prompt_tokens")
    if pt is None:
        raise NimProbeError(
            "Missing usage.prompt_tokens — cannot qualify",
            raw=parsed,
        )
    details = {
        "prompt_tokens": int(pt),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "prompt_tokens_details": usage.get("prompt_tokens_details"),
        "completion_tokens_details": usage.get("completion_tokens_details"),
        "model": parsed.get("model"),
        "id": parsed.get("id"),
        "system_fingerprint": parsed.get("system_fingerprint"),
        "finish_reason": None,
    }
    choices = parsed.get("choices") or []
    if choices and isinstance(choices[0], dict):
        details["finish_reason"] = choices[0].get("finish_reason")
        msg = choices[0].get("message") or {}
        # Do not store full content; only note emptiness / reasoning presence
        details["assistant_content_len"] = len(msg.get("content") or "")
        details["reasoning_content_present"] = msg.get("reasoning_content") is not None
    return int(pt), details


def load_api_key(env_name: str = "NIM_API_KEY") -> str:
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise NimProbeError(f"{env_name} not set in environment")
    return key
