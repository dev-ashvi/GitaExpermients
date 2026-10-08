#!/usr/bin/env python3
"""Bounded NVIDIA free-NIM generation-load screen: 60s start-to-start, max 24.

Non-scientific. Alternating Actor/Witness-shaped engineering prompts with
substantial max_tokens. No retries. Stop on first 429. Does not print API keys.
Does not launch Experiment 0.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiment1"))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0 import engineering_config as eng
from experiment0.archival import ArchivedRunError, assert_not_archived_for_resume
from experiment0.qualification_fixtures.nim_count_once import (
    NimProbeError,
    extract_prompt_tokens,
    load_api_key,
    post_chat_completions_once,
)
from config.experiment_config import FROZEN_MANIFEST
from src.types_util import validate_input_integrity

e0 = load_experiment0_config()
FX_DIR = REPO / "experiment0" / "qualification_fixtures"
EVIDENCE_PATH = (
    REPO
    / "experiment0"
    / "tokenizers"
    / "nemotron3_super_120b_bf16"
    / "QUALIFICATION_EVIDENCE.json"
)

MAX_ATTEMPTS = 24
TARGET_START_TO_START_SEC = 60.0
MODEL = "nvidia/nemotron-3-super-120b-a12b"
ACTOR_MAX_TOKENS = 800
WITNESS_MAX_TOKENS = 1600
# Predetermined representativeness thresholds (frozen before first call).
OUTPUT_BUDGET_SUM = 12 * ACTOR_MAX_TOKENS + 12 * WITNESS_MAX_TOKENS  # 28800
MIN_TOTAL_COMPLETION = OUTPUT_BUDGET_SUM // 2  # 14400
MIN_ACTOR_COMPLETION = (12 * ACTOR_MAX_TOKENS) // 2  # 4800
MIN_WITNESS_COMPLETION = (12 * WITNESS_MAX_TOKENS) // 2  # 9600

# Rotate base large-context fixtures so prefixes are not identical every call.
ACTOR_FIXTURES = (
    "worst_case_actor",
    "short_actor_t1",
    "multi_message_actor",
    "revision_shaped_actor",
)
WITNESS_FIXTURES = (
    "worst_case_witness",
    "short_witness",
)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _redact(s: str) -> str:
    out = s
    marker = "nvapi-"
    while marker in out:
        i = out.index(marker)
        j = i + len(marker)
        while j < len(out) and out[j] not in " \n\r\t\"'":
            j += 1
        out = out[:i] + "nvapi-[REDACTED]" + out[j:]
    return out


def _body_hash(body: dict[str, Any]) -> str:
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def actor_gen_prompt(slot: int) -> str:
    """Synthetic Actor-shaped engineering load — not scientific measurement."""
    # Distinct per slot to diversify the uncached suffix.
    n_records = 36 + (slot % 5)  # 36–40
    return (
        "ENGINEERING LOAD QUALIFICATION ONLY. Ignore any prior task framing "
        "in this conversation. Do not evaluate sources, health claims, "
        "reward, obstruction, or research outcomes.\n\n"
        f"Produce exactly {n_records} numbered synthetic telemetry records "
        f"(slot={slot:02d}). Each record MUST use this exact line format:\n"
        "REC|<id>|ISO8601|<metric>|float|<unit>|<status>|<one_sentence_note>\n"
        "Use only fictional values. No citations. No blank lines between records. "
        f"Continue until all {n_records} records are complete. After the last "
        "record, append one line: END_OF_RECORDS."
    )


def witness_gen_prompt(slot: int) -> str:
    """Synthetic Witness-shaped engineering load — not scientific evaluation."""
    n_entries = 20 + (slot % 6)  # 20–25
    topics = (
        "queue backpressure",
        "replica lag",
        "checksum mismatch",
        "lease expiry",
        "shard rebalance",
        "cold-start latency",
    )
    topic = topics[slot % len(topics)]
    return (
        "ENGINEERING LOAD QUALIFICATION ONLY. Ignore any prior Witness or "
        "evaluation framing. Do not score Actor answers, manipulation "
        "conditions, or scientific truth claims.\n\n"
        f"Write a structured technical glossary with exactly {n_entries} "
        f"entries about generic distributed-systems failure modes "
        f"(focus theme: {topic}; slot={slot:02d}). "
        "Each entry MUST use this block format:\n"
        "ENTRY <n>\n"
        "TERM: <name>\n"
        "DEFINITION: <3 to 5 complete sentences>\n"
        "RELATED: <three comma-separated terms>\n"
        "NOTES: <exactly two complete sentences>\n"
        "Use only synthetic/engineering content. No scientific measurements. "
        f"Continue until all {n_entries} entries are complete, then append "
        "END_OF_GLOSSARY."
    )


def build_frozen_sequence() -> list[dict[str, Any]]:
    """Predetermined 24-call sequence: Actor/Witness alternating."""
    seq: list[dict[str, Any]] = []
    for i in range(1, MAX_ATTEMPTS + 1):
        role = "actor" if (i % 2 == 1) else "witness"
        if role == "actor":
            slot = (i + 1) // 2  # 1..12
            fixture_id = ACTOR_FIXTURES[(slot - 1) % len(ACTOR_FIXTURES)]
            max_tokens = ACTOR_MAX_TOKENS
            user_content = actor_gen_prompt(slot)
        else:
            slot = i // 2  # 1..12
            fixture_id = WITNESS_FIXTURES[(slot - 1) % len(WITNESS_FIXTURES)]
            max_tokens = WITNESS_MAX_TOKENS
            user_content = witness_gen_prompt(slot)

        fixture = json.loads((FX_DIR / f"{fixture_id}.json").read_text(encoding="utf-8"))
        base_body = fixture["provider_facing_request_body"]
        messages = deepcopy(base_body["messages"])
        # Preserve large-context bodies:
        # - Actor fixtures: last user turn is a short instruction; replace it.
        # - Witness fixtures: last user turn IS the large source packet; append
        #   the engineering generation prompt so ~168k–208k input is retained.
        # Never inject Witness evaluation content into Actor fixtures.
        if not messages or messages[-1].get("role") != "user":
            messages.append({"role": "user", "content": user_content})
        elif role == "witness":
            prior = messages[-1].get("content") or ""
            messages[-1] = {
                "role": "user",
                "content": prior + "\n\n" + user_content,
            }
        else:
            messages[-1] = {"role": "user", "content": user_content}

        body = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        # Fail closed if Witness large packet was accidentally dropped.
        if role == "witness":
            last_len = len((messages[-1].get("content") or ""))
            if last_len < 100_000:
                raise RuntimeError(
                    f"Witness attempt {i} content too small ({last_len} chars) — "
                    "large-context packet must be preserved"
                )
        seq.append(
            {
                "attempt_index": i,
                "role_shaped": role,
                "slot": slot,
                "fixture_id": fixture_id,
                "base_fixture_body_sha256": fixture.get(
                    "provider_facing_request_body_sha256"
                ),
                "base_local_prompt_tokens": fixture.get("local_prompt_tokens"),
                "max_tokens": max_tokens,
                "enable_thinking": False,
                "generation_prompt_sha256": hashlib.sha256(
                    user_content.encode("utf-8")
                ).hexdigest(),
                "request_body_sha256": _body_hash(body),
                "n_messages": len(messages),
                # Body stored for execution; not scientific content logging.
                "_body": body,
                "_generation_prompt": user_content,
            }
        )
    return seq


def preflight() -> dict[str, Any]:
    verified = validate_input_integrity()
    if set(verified.keys()) != set(FROZEN_MANIFEST.keys()) or len(verified) != 14:
        raise RuntimeError(f"FROZEN_MANIFEST mismatch: {len(verified)}/14")

    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    if evidence.get("hosted_qualification_status") != "PASSED":
        raise RuntimeError("Tokenizer qualification not PASSED for nvidia-nim")
    if evidence.get("provider_profile") != "nvidia-nim":
        raise RuntimeError("Unexpected tokenizer provider_profile")
    if not evidence.get("evidence_validated"):
        raise RuntimeError("Tokenizer evidence_validated is false")

    idx = json.loads((FX_DIR / "INDEX.json").read_text(encoding="utf-8"))
    fixture_checks = []
    for f in idx["fixtures"]:
        path = FX_DIR / f"{f['fixture_id']}.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        h = _body_hash(d["provider_facing_request_body"])
        ok = (
            h == f["body_sha256"]
            and h == d.get("provider_facing_request_body_sha256")
            and int(d["local_prompt_tokens"]) == int(f["local_prompt_tokens"])
        )
        fixture_checks.append({"fixture_id": f["fixture_id"], "hash_ok": ok})
        if not ok:
            raise RuntimeError(f"Fixture hash mismatch: {f['fixture_id']}")

    archived_id = eng.EXCLUDED_FROM_CLEAN_N60_RUN_IDS[0]
    archived_dir = REPO / "experiment0" / "runs" / archived_id
    if not archived_dir.exists():
        # Also accept alternate runs location if present
        candidates = list(REPO.glob(f"**/runs/{archived_id}"))
        archived_dir = candidates[0] if candidates else archived_dir
    try:
        assert_not_archived_for_resume(archived_dir)
        archived_blocked = False
    except ArchivedRunError:
        archived_blocked = True
    if not archived_blocked:
        raise RuntimeError(
            f"Archived run {archived_id} was NOT blocked by resume guard"
        )

    if eng.PER_REQUEST_TOKEN_COUNT_MODE != "unavailable":
        raise RuntimeError(
            f"Unexpected PER_REQUEST_TOKEN_COUNT_MODE="
            f"{eng.PER_REQUEST_TOKEN_COUNT_MODE}"
        )
    if eng.ACTIVE_PROVIDER_PROFILE != "nvidia-nim":
        raise RuntimeError("ACTIVE_PROVIDER_PROFILE is not nvidia-nim")

    # Confirm single-shot client has no retry loop (source contract).
    import inspect

    src = inspect.getsource(post_chat_completions_once)
    if "No nested retries" not in src or "No 429 retry" not in src:
        raise RuntimeError("Client contract text missing no-retry guarantees")
    if "for " in src and "range" in src and "retry" in src.lower():
        raise RuntimeError("Client appears to contain a retry loop")

    key_present = bool(__import__("os").environ.get(e0.NIM_API_KEY_ENV, "").strip())
    if not key_present:
        raise RuntimeError(f"{e0.NIM_API_KEY_ENV} not set")

    return {
        "frozen_manifest": "14/14",
        "tokenizer_qualification": "PASSED",
        "tokenizer_revision": evidence.get("tokenizer_revision"),
        "chat_template_sha256": evidence.get("chat_template_sha256"),
        "artifact_hashes": evidence.get("artifact_hashes"),
        "archived_run_excluded": list(eng.EXCLUDED_FROM_CLEAN_N60_RUN_IDS),
        "archived_resume_blocked": True,
        "fixture_checks": fixture_checks,
        "per_request_token_count_mode": eng.PER_REQUEST_TOKEN_COUNT_MODE,
        "active_provider_profile": eng.ACTIVE_PROVIDER_PROFILE,
        "client": "post_chat_completions_once",
        "retries": 0,
        "paid_provider_selected": False,
        "scientific_schedule_used": False,
        "key_env_present": True,
        "key_value_logged": False,
        "free_entitlement_note": (
            "Same integrate.api.nvidia.com NIM path used for prior free-tier "
            "Exp0/diagnostics and the passed large-input endurance screen; "
            "no OpenRouter/DeepInfra/paid provider configured for this task. "
            "Account billing portal not queried; stop if charges are later "
            "discovered."
        ),
        "success_criteria_frozen": {
            "all_24_http_200": True,
            "no_http_429": True,
            "model_identity": MODEL,
            "min_total_completion_tokens": MIN_TOTAL_COMPLETION,
            "min_actor_completion_tokens": MIN_ACTOR_COMPLETION,
            "min_witness_completion_tokens": MIN_WITNESS_COMPLETION,
            "output_budget_sum": OUTPUT_BUDGET_SUM,
        },
    }


def classify(
    *,
    successes: int,
    stop_reason: str,
    actor_out: int,
    witness_out: int,
    total_out: int,
) -> str:
    if stop_reason == "HTTP_429":
        return "NVIDIA_GENERATION_SCREEN_FAILED_RATE_LIMIT"
    if stop_reason in {
        "MODEL_MISMATCH",
        "MISSING_USAGE",
        "INTEGRITY",
        "UNEXPECTED",
        "PROVIDER_FAIL",
        "TEMPLATE_OR_TRUNCATION",
    }:
        return "NVIDIA_GENERATION_SCREEN_FAILED_INTEGRITY"
    if successes == MAX_ATTEMPTS and stop_reason == "COMPLETED_24":
        if (
            total_out >= MIN_TOTAL_COMPLETION
            and actor_out >= MIN_ACTOR_COMPLETION
            and witness_out >= MIN_WITNESS_COMPLETION
        ):
            return "NVIDIA_GENERATION_SCREEN_PASSED"
        return "NVIDIA_GENERATION_SCREEN_INCONCLUSIVE"
    return "NVIDIA_GENERATION_SCREEN_FAILED_INTEGRITY"


def main() -> int:
    pre = preflight()
    sequence = build_frozen_sequence()

    run_id = datetime.now(timezone.utc).strftime("nim_generation_%Y%m%dT%H%M%SZ")
    out_dir = REPO / "diagnostics" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    # Freeze plan BEFORE first HTTP call.
    freeze = {
        "diagnostic": "nvidia_free_nim_generation_screen_60s",
        "run_id": run_id,
        "frozen_utc": _utc(),
        "model": MODEL,
        "base_url": e0.NIM_BASE_URL,
        "max_attempts": MAX_ATTEMPTS,
        "target_start_to_start_sec": TARGET_START_TO_START_SEC,
        "actor_max_tokens": ACTOR_MAX_TOKENS,
        "witness_max_tokens": WITNESS_MAX_TOKENS,
        "retries": 0,
        "adaptive_pacing": False,
        "overlap": False,
        "scientific": False,
        "preflight": pre,
        "sequence": [
            {k: v for k, v in item.items() if not k.startswith("_")}
            for item in sequence
        ],
    }
    (out_dir / "FROZEN_PLAN.json").write_text(
        json.dumps(freeze, indent=2), encoding="utf-8"
    )
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "diagnostic": freeze["diagnostic"],
                "run_id": run_id,
                "model": MODEL,
                "started_utc": _utc(),
                "free_entitlement_note": pre["free_entitlement_note"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[generation] frozen plan written: {out_dir / 'FROZEN_PLAN.json'}",
        flush=True,
    )
    print(json.dumps({"preflight": "OK", **{k: pre[k] for k in (
        "frozen_manifest",
        "tokenizer_qualification",
        "archived_resume_blocked",
        "retries",
        "paid_provider_selected",
    )}}, indent=2), flush=True)

    key = load_api_key(e0.NIM_API_KEY_ENV)
    attempts: list[dict[str, Any]] = []
    cumulative_input = 0
    cumulative_output = 0
    actor_out = 0
    witness_out = 0
    successes = 0
    t_wall0 = time.monotonic()
    next_sched = time.monotonic()
    stop_reason = "COMPLETED_24"
    classification = "NVIDIA_GENERATION_SCREEN_PASSED"

    for item in sequence:
        i = item["attempt_index"]
        now = time.monotonic()
        if now < next_sched:
            time.sleep(next_sched - now)
        actual_start_mono = time.monotonic()
        scheduled_start_mono = next_sched
        next_sched = actual_start_mono + TARGET_START_TO_START_SEC

        inter = None
        if attempts:
            inter = actual_start_mono - attempts[-1]["_actual_start_mono"]

        rec: dict[str, Any] = {
            "attempt_index": i,
            "role_shaped": item["role_shaped"],
            "slot": item["slot"],
            "fixture_id": item["fixture_id"],
            "max_tokens": item["max_tokens"],
            "request_body_sha256": item["request_body_sha256"],
            "generation_prompt_sha256": item["generation_prompt_sha256"],
            "scheduled_start_utc": _utc(),
            "actual_start_utc": _utc(),
            "actual_inter_request_interval_sec": inter,
            "target_start_to_start_sec": TARGET_START_TO_START_SEC,
            "_actual_start_mono": actual_start_mono,
            "drift_from_schedule_sec": actual_start_mono - scheduled_start_mono,
        }
        print(
            f"[generation] attempt={i}/{MAX_ATTEMPTS} role={item['role_shaped']} "
            f"fixture={item['fixture_id']} max_tokens={item['max_tokens']} "
            f"inter={inter}",
            flush=True,
        )

        t0 = time.monotonic()
        try:
            parsed = post_chat_completions_once(
                base_url=e0.NIM_BASE_URL,
                api_key=key,
                body=item["_body"],
                timeout_sec=1200.0,
            )
            pt, details = extract_prompt_tokens(parsed)
            dur = time.monotonic() - t0
            model_ret = details.get("model")
            if model_ret and model_ret != MODEL:
                rec.update(
                    {
                        "http_status": 200,
                        "duration_sec": round(dur, 3),
                        "status": "FAIL_MODEL_MISMATCH",
                        "model_returned": model_ret,
                        "provider_prompt_tokens": pt,
                        "request_id": details.get("id"),
                    }
                )
                attempts.append(rec)
                (out_dir / f"attempt_{i:02d}.json").write_text(
                    json.dumps(
                        {k: v for k, v in rec.items() if not k.startswith("_")},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                stop_reason = "MODEL_MISMATCH"
                classification = "NVIDIA_GENERATION_SCREEN_FAILED_INTEGRITY"
                print("[generation] STOP model mismatch", flush=True)
                break

            ptd = details.get("prompt_tokens_details") or {}
            cached = ptd.get("cached_tokens") if isinstance(ptd, dict) else None
            out_tok = int(details.get("completion_tokens") or 0)
            finish = details.get("finish_reason")
            # Unexpected finish: content filter / error-like; length is OK for load.
            if finish not in ("stop", "length", None):
                rec.update(
                    {
                        "http_status": 200,
                        "duration_sec": round(dur, 3),
                        "status": "FAIL_UNEXPECTED_FINISH",
                        "finish_reason": finish,
                        "request_id": details.get("id"),
                        "input_tokens": pt,
                        "cached_tokens": cached,
                        "output_tokens": out_tok,
                        "model_returned": model_ret,
                    }
                )
                attempts.append(rec)
                (out_dir / f"attempt_{i:02d}.json").write_text(
                    json.dumps(
                        {k: v for k, v in rec.items() if not k.startswith("_")},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                stop_reason = "TEMPLATE_OR_TRUNCATION"
                classification = "NVIDIA_GENERATION_SCREEN_FAILED_INTEGRITY"
                print(f"[generation] STOP unexpected finish_reason={finish}", flush=True)
                break

            cumulative_input += int(pt)
            cumulative_output += out_tok
            if item["role_shaped"] == "actor":
                actor_out += out_tok
            else:
                witness_out += out_tok
            successes += 1
            non_cached = int(pt) - int(cached) if cached is not None else None
            rec.update(
                {
                    "http_status": 200,
                    "duration_sec": round(dur, 3),
                    "status": "OK",
                    "request_id": details.get("id"),
                    "input_tokens": pt,
                    "cached_tokens": cached,
                    "non_cached_prompt_tokens": non_cached,
                    "output_tokens": out_tok,
                    "model_returned": model_ret,
                    "finish_reason": finish,
                    "assistant_content_len": details.get("assistant_content_len"),
                    "reasoning_content_present": details.get(
                        "reasoning_content_present"
                    ),
                    "cumulative_accepted_input_tokens": cumulative_input,
                    "cumulative_output_tokens": cumulative_output,
                    "cumulative_actor_output_tokens": actor_out,
                    "cumulative_witness_output_tokens": witness_out,
                    "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
                }
            )
            attempts.append(rec)
            (out_dir / f"attempt_{i:02d}.json").write_text(
                json.dumps(
                    {k: v for k, v in rec.items() if not k.startswith("_")},
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                f"[generation] OK in={pt} cached={cached} out={out_tok} "
                f"finish={finish} dur={dur:.2f}s cum_out={cumulative_output}",
                flush=True,
            )
        except NimProbeError as exc:
            dur = time.monotonic() - t0
            # Missing usage surfaces as NimProbeError from extract_prompt_tokens
            status = "RATE_LIMITED" if exc.rate_limited else "PROVIDER_FAIL"
            if "Missing usage" in str(exc):
                status = "MISSING_USAGE"
                stop_reason = "MISSING_USAGE"
            elif exc.rate_limited:
                stop_reason = "HTTP_429"
            else:
                stop_reason = "PROVIDER_FAIL"
            rec.update(
                {
                    "http_status": exc.status_code,
                    "duration_sec": round(dur, 3),
                    "status": status,
                    "rate_limited": bool(exc.rate_limited),
                    "error_redacted": _redact(str(exc))[:800],
                    "error_body_redacted": _redact(str(exc.raw)[:500])
                    if exc.raw
                    else None,
                    "cumulative_accepted_input_tokens": cumulative_input,
                    "cumulative_output_tokens": cumulative_output,
                    "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
                }
            )
            attempts.append(rec)
            (out_dir / f"attempt_{i:02d}.json").write_text(
                json.dumps(
                    {k: v for k, v in rec.items() if not k.startswith("_")},
                    indent=2,
                ),
                encoding="utf-8",
            )
            classification = classify(
                successes=successes,
                stop_reason=stop_reason,
                actor_out=actor_out,
                witness_out=witness_out,
                total_out=cumulative_output,
            )
            print(
                f"[generation] STOP {stop_reason} status={exc.status_code}",
                flush=True,
            )
            break
        except Exception as exc:  # noqa: BLE001
            dur = time.monotonic() - t0
            rec.update(
                {
                    "http_status": None,
                    "duration_sec": round(dur, 3),
                    "status": "UNEXPECTED",
                    "error_redacted": _redact(str(exc))[:800],
                    "cumulative_accepted_input_tokens": cumulative_input,
                    "cumulative_output_tokens": cumulative_output,
                    "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
                }
            )
            attempts.append(rec)
            (out_dir / f"attempt_{i:02d}.json").write_text(
                json.dumps(
                    {k: v for k, v in rec.items() if not k.startswith("_")},
                    indent=2,
                ),
                encoding="utf-8",
            )
            stop_reason = "UNEXPECTED"
            classification = "NVIDIA_GENERATION_SCREEN_FAILED_INTEGRITY"
            print(f"[generation] STOP unexpected: {exc}", flush=True)
            break
    else:
        stop_reason = "COMPLETED_24"
        classification = classify(
            successes=successes,
            stop_reason=stop_reason,
            actor_out=actor_out,
            witness_out=witness_out,
            total_out=cumulative_output,
        )

    clean = [{k: v for k, v in a.items() if not k.startswith("_")} for a in attempts]
    intervals = [
        a["actual_inter_request_interval_sec"]
        for a in clean
        if a.get("actual_inter_request_interval_sec") is not None
    ]
    durations = [a["duration_sec"] for a in clean if a.get("duration_sec") is not None]
    actor_outs = [
        a["output_tokens"]
        for a in clean
        if a.get("status") == "OK" and a.get("role_shaped") == "actor"
    ]
    witness_outs = [
        a["output_tokens"]
        for a in clean
        if a.get("status") == "OK" and a.get("role_shaped") == "witness"
    ]
    cached_vals = [
        a["cached_tokens"]
        for a in clean
        if a.get("status") == "OK" and a.get("cached_tokens") is not None
    ]

    summary = {
        "diagnostic": "nvidia_free_nim_generation_screen_60s",
        "run_id": run_id,
        "model": MODEL,
        "base_url": e0.NIM_BASE_URL,
        "ended_utc": _utc(),
        "classification": classification,
        "stop_reason": stop_reason,
        "attempts_total": len(clean),
        "successes": successes,
        "failures": len(clean) - successes,
        "cumulative_accepted_input_tokens": cumulative_input,
        "cumulative_output_tokens": cumulative_output,
        "actor_output_tokens_total": actor_out,
        "witness_output_tokens_total": witness_out,
        "output_budget_sum": OUTPUT_BUDGET_SUM,
        "representativeness": {
            "min_total_completion_tokens": MIN_TOTAL_COMPLETION,
            "min_actor_completion_tokens": MIN_ACTOR_COMPLETION,
            "min_witness_completion_tokens": MIN_WITNESS_COMPLETION,
            "total_met": cumulative_output >= MIN_TOTAL_COMPLETION,
            "actor_met": actor_out >= MIN_ACTOR_COMPLETION,
            "witness_met": witness_out >= MIN_WITNESS_COMPLETION,
            "actor_output_min_mean_max": (
                [min(actor_outs), sum(actor_outs) / len(actor_outs), max(actor_outs)]
                if actor_outs
                else None
            ),
            "witness_output_min_mean_max": (
                [
                    min(witness_outs),
                    sum(witness_outs) / len(witness_outs),
                    max(witness_outs),
                ]
                if witness_outs
                else None
            ),
        },
        "caching": {
            "cached_min_max": [min(cached_vals), max(cached_vals)]
            if cached_vals
            else None,
            "n_with_cached_field": len(cached_vals),
        },
        "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
        "pacing": {
            "target_start_to_start_sec": TARGET_START_TO_START_SEC,
            "n_intervals": len(intervals),
            "min_interval_sec": min(intervals) if intervals else None,
            "max_interval_sec": max(intervals) if intervals else None,
            "mean_interval_sec": (sum(intervals) / len(intervals)) if intervals else None,
            "duration_min_mean_max": (
                [min(durations), sum(durations) / len(durations), max(durations)]
                if durations
                else None
            ),
        },
        "first_failure": next((a for a in clean if a.get("status") != "OK"), None),
        "preflight": pre,
        "attempts": clean,
        "limits_of_inference": (
            "Bounded 24-call generation screen at 60s spacing only. Does not "
            "prove ~3100-call Exp0 scientific capacity, dense mid-episode "
            "pacing, nested retries, or multi-day continuity."
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "classification": classification,
                "stop_reason": stop_reason,
                "attempts": len(clean),
                "successes": successes,
                "cum_input": cumulative_input,
                "cum_output": cumulative_output,
                "actor_out": actor_out,
                "witness_out": witness_out,
                "out_dir": str(out_dir),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if classification == "NVIDIA_GENERATION_SCREEN_PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
