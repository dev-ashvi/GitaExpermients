#!/usr/bin/env python3
"""Standalone NIM / NVIDIA OpenAI-compatible availability diagnostic.

Does not import Experiment 0/1 harness code.
Does not hardcode API keys.
Does not infer context-window size, free-tier eligibility, or rate limits
unless the API explicitly returns that information.

Usage:
  set NIM_API_KEY=...
  python scripts/check_nim_availability.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

# NVIDIA hosted OpenAI-compatible NIM endpoint
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

CANDIDATE_MODEL_IDS = [
    "nvidia/nemotron-super-49b-v1",
    "nvidia/nemotron-3-super-120b-a12b",
    "deepseek-ai/deepseek-v4-flash-0731",
    "deepseek-ai/deepseek-r1-0528",
    "meta/llama-3.1-405b-instruct",
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-70b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
]

JSON_PROBE_USER = (
    'Respond with ONLY valid JSON matching this schema and nothing else: '
    '{"ok": true, "model_probe": "nim-diagnostic"}'
)

MAX_RESPONSE_DISPLAY_CHARS = 2000
REQUEST_TIMEOUT_SEC = 120


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _http_json(
    method: str,
    url: str,
    api_key: str,
    body: Optional[dict[str, Any]] = None,
) -> tuple[int, Any, Optional[str], float]:
    """Return (http_status, parsed_json_or_None, raw_text_or_error, latency_sec)."""
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=_auth_headers(api_key),
        method=method,
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            latency = time.perf_counter() - t0
            status = int(getattr(resp, "status", 200) or 200)
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            return status, parsed, raw, latency
    except urllib.error.HTTPError as e:
        latency = time.perf_counter() - t0
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return int(e.code), parsed, raw or str(e), latency
    except Exception as e:  # noqa: BLE001 — diagnostic surface
        latency = time.perf_counter() - t0
        return -1, None, f"{type(e).__name__}: {e}", latency


def list_model_ids(api_key: str) -> tuple[list[str], dict[str, Any]]:
    status, parsed, raw, latency = _http_json(
        "GET", f"{NIM_BASE_URL}/models", api_key
    )
    meta: dict[str, Any] = {
        "http_status": status,
        "latency_sec": round(latency, 3),
        "error": None,
        "raw_preview": None,
    }
    ids: list[str] = []
    if status != 200 or not isinstance(parsed, dict):
        meta["error"] = f"models list failed status={status}"
        meta["raw_preview"] = (raw or "")[:MAX_RESPONSE_DISPLAY_CHARS]
        return ids, meta
    data = parsed.get("data")
    if not isinstance(data, list):
        meta["error"] = "models response missing data[]"
        meta["raw_preview"] = (raw or "")[:MAX_RESPONSE_DISPLAY_CHARS]
        return ids, meta
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    ids = sorted(set(ids))
    return ids, meta


def extract_assistant_text(chat_payload: Any) -> str:
    if not isinstance(chat_payload, dict):
        return ""
    choices = chat_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice0 = choices[0]
    if not isinstance(choice0, dict):
        return ""
    message = choice0.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        # Some models return content as a list of parts
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            return "".join(parts)
    # completions-style fallback
    text = choice0.get("text")
    return text if isinstance(text, str) else ""


def looks_like_json(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    # Strip common markdown fences if present
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


def probe_model(api_key: str, model_id: str) -> dict[str, Any]:
    body = {
        "model": model_id,
        "temperature": 0,
        "max_tokens": 128,
        "messages": [
            {
                "role": "user",
                "content": JSON_PROBE_USER,
            }
        ],
    }
    status, parsed, raw, latency = _http_json(
        "POST",
        f"{NIM_BASE_URL}/chat/completions",
        api_key,
        body=body,
    )
    assistant = extract_assistant_text(parsed) if status == 200 else ""
    display = assistant if assistant else (raw or "")
    if len(display) > MAX_RESPONSE_DISPLAY_CHARS:
        display = display[:MAX_RESPONSE_DISPLAY_CHARS] + "…[truncated]"
    err = None
    if status != 200:
        if isinstance(parsed, dict) and "error" in parsed:
            err = parsed["error"]
        else:
            err = (raw or f"HTTP {status}")[:MAX_RESPONSE_DISPLAY_CHARS]
    return {
        "model_id": model_id,
        "call_succeeded": status == 200 and bool(assistant),
        "http_status": status,
        "api_error": err,
        "valid_json_returned": looks_like_json(assistant) if assistant else False,
        "latency_sec": round(latency, 3),
        "response_text": display,
    }


def main() -> int:
    api_key = os.environ.get("NIM_API_KEY", "").strip()
    if not api_key:
        print(
            "NIM_API_KEY is not set.\n"
            "Export NIM_API_KEY to your NVIDIA API key, then re-run:\n"
            "  python scripts/check_nim_availability.py\n"
            "No API calls were made."
        )
        return 2

    print(f"NIM base URL: {NIM_BASE_URL}")
    print("Listing models via GET /v1/models …")
    listed_ids, list_meta = list_model_ids(api_key)
    if list_meta.get("error"):
        print(f"Model list error: {list_meta['error']}")
        if list_meta.get("raw_preview"):
            print(f"Preview: {list_meta['raw_preview']}")
        print("Continuing candidate probes anyway (listed=unknown/no).")
    else:
        print(f"Models returned by API: {len(listed_ids)}")
        for mid in listed_ids:
            print(f"  - {mid}")

    listed_set = set(listed_ids)
    rows: list[dict[str, Any]] = []
    print("\nCandidate probes (minimal JSON-output chat completion):")
    for model_id in CANDIDATE_MODEL_IDS:
        listed = model_id in listed_set if listed_ids else False
        # If list failed entirely, mark listed as no (cannot confirm presence)
        if list_meta.get("error") and not listed_ids:
            listed_display = "no (list failed)"
            listed_bool = False
        else:
            listed_display = "yes" if listed else "no"
            listed_bool = listed

        print(f"\n=== {model_id} ===")
        print(f"listed_by_api: {listed_display}")
        result = probe_model(api_key, model_id)
        result["listed_by_api"] = listed_bool
        rows.append(result)
        print(f"call_succeeded: {'yes' if result['call_succeeded'] else 'no'}")
        print(f"http_status: {result['http_status']}")
        if result["api_error"] is not None:
            print(f"api_error: {result['api_error']}")
        print(f"valid_json_returned: {'yes' if result['valid_json_returned'] else 'no'}")
        print(f"latency_sec: {result['latency_sec']}")
        print(f"response_text: {result['response_text']}")

    print("\n=== SUMMARY TABLE ===")
    print(
        f"{'model_id':<48} {'listed':<6} {'call_ok':<8} "
        f"{'json_ok':<8} {'latency':>8}  error"
    )
    for r in rows:
        err = r["api_error"]
        if isinstance(err, dict):
            err_s = json.dumps(err, ensure_ascii=False)[:80]
        else:
            err_s = (str(err) if err is not None else "")[:80]
        print(
            f"{r['model_id']:<48} "
            f"{'yes' if r['listed_by_api'] else 'no':<6} "
            f"{'yes' if r['call_succeeded'] else 'no':<8} "
            f"{'yes' if r['valid_json_returned'] else 'no':<8} "
            f"{r['latency_sec']:>8.3f}  {err_s}"
        )

    # Machine-readable block for operators (no secrets)
    out = {
        "base_url": NIM_BASE_URL,
        "models_list_meta": {k: v for k, v in list_meta.items() if k != "raw_preview"},
        "listed_model_count": len(listed_ids),
        "listed_model_ids": listed_ids,
        "candidates": rows,
    }
    print("\n=== JSON SUMMARY ===")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
