#!/usr/bin/env python3
"""Run exactly one NIM token-count probe (no retries). Exit codes:
0 = pass (delta==0)
2 = mismatch / integrity
3 = rate limited
4 = other provider/transport failure
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiment1"))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.local_nemotron_counter import LocalNemotronChatTokenCounter
from experiment0.qualification_fixtures.nim_count_once import (
    NimProbeError,
    extract_prompt_tokens,
    load_api_key,
    post_chat_completions_once,
)

e0 = load_experiment0_config()
FX_DIR = Path(__file__).resolve().parent
RESULTS_DIR = FX_DIR / "nim_probe_results"


def _body_hash(body: dict[str, Any]) -> str:
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixture-id", required=True)
    args = p.parse_args()
    fx_path = FX_DIR / f"{args.fixture_id}.json"
    if not fx_path.exists():
        print(json.dumps({"status": "FAIL_INTEGRITY", "error": f"missing {fx_path}"}))
        return 2

    fixture = json.loads(fx_path.read_text(encoding="utf-8"))
    body = fixture["provider_facing_request_body"]
    expected_hash = fixture["provider_facing_request_body_sha256"]
    actual_hash = _body_hash(body)
    if actual_hash != expected_hash:
        print(
            json.dumps(
                {
                    "status": "FAIL_INTEGRITY",
                    "error": "fixture body hash mismatch",
                    "expected": expected_hash,
                    "actual": actual_hash,
                }
            )
        )
        return 2

    # Independent local recount from body messages (system is first message)
    messages = list(body["messages"])
    system = ""
    rest = messages
    if messages and messages[0].get("role") == "system":
        system = messages[0]["content"]
        rest = messages[1:]

    counter = LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim",
        model_id=e0.ACTOR_MODEL,
        enable_thinking=False,
        load_evidence=False,
    )
    local_n, trust = counter.count_prompt_tokens(system, rest)
    # Cross-check fixture stored local count (should match; warn if not)
    stored = fixture.get("local_prompt_tokens")

    # Count-only body: identical messages + chat_template_kwargs; max_tokens=1 only
    probe_body = {
        "model": body["model"],
        "messages": body["messages"],  # exact list
        "max_tokens": 1,
        "temperature": 0.0,
        "chat_template_kwargs": dict(body.get("chat_template_kwargs") or {"enable_thinking": False}),
    }
    # Ensure thinking false
    probe_body["chat_template_kwargs"]["enable_thinking"] = False

    # Verify transport payload hash of messages+kwargs identity (messages unchanged)
    if probe_body["messages"] != body["messages"]:
        print(json.dumps({"status": "FAIL_INTEGRITY", "error": "messages altered"}))
        return 2

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    record: dict[str, Any] = {
        "fixture_id": args.fixture_id,
        "timestamp_utc": ts,
        "fixture_body_sha256": expected_hash,
        "local_prompt_tokens": local_n,
        "local_token_trust": trust.value,
        "fixture_stored_local_prompt_tokens": stored,
        "tokenizer_revision": counter._pinning.get("huggingface_revision"),
        "chat_template_sha256": counter.chat_template_sha256,
        "probe_max_tokens": 1,
        "enable_thinking": False,
        "provider_profile": "nvidia-nim",
        "base_url": e0.NIM_BASE_URL,
        "retries": 0,
    }

    try:
        key = load_api_key(e0.NIM_API_KEY_ENV)
        parsed = post_chat_completions_once(
            base_url=e0.NIM_BASE_URL,
            api_key=key,
            body=probe_body,
            timeout_sec=600.0,
        )
        provider_n, meta = extract_prompt_tokens(parsed)
    except NimProbeError as exc:
        record["status"] = "RATE_LIMITED" if exc.rate_limited else "PROVIDER_FAIL"
        record["error"] = str(exc)[:800]
        record["status_code"] = exc.status_code
        record["rate_limited"] = bool(exc.rate_limited)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{args.fixture_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(json.dumps({k: record[k] for k in record if k != "error"} | {"error": record.get("error", "")[:200]}))
        return 3 if exc.rate_limited else 4

    delta = int(local_n) - int(provider_n)
    record["provider_prompt_tokens"] = provider_n
    record["delta"] = delta
    record["provider_meta"] = meta
    # Cached tokens note
    ptd = (meta.get("prompt_tokens_details") or {}) if isinstance(meta, dict) else {}
    record["cached_tokens"] = ptd.get("cached_tokens") if isinstance(ptd, dict) else None
    record["model_returned"] = meta.get("model")
    record["request_id"] = meta.get("id")

    if meta.get("model") and meta.get("model") != e0.ACTOR_MODEL:
        record["status"] = "FAIL_MODEL_MISMATCH"
        record["error"] = f"model_returned={meta.get('model')}"
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{args.fixture_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(json.dumps(record, indent=2)[:2000])
        return 2

    if delta != 0:
        record["status"] = "FAIL_DELTA"
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{args.fixture_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(json.dumps(record, indent=2)[:2000])
        return 2

    record["status"] = "PASS"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{args.fixture_id}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "fixture_id": args.fixture_id,
                "local": local_n,
                "provider": provider_n,
                "delta": delta,
                "cached_tokens": record["cached_tokens"],
                "request_id": record["request_id"],
                "model_returned": record["model_returned"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
