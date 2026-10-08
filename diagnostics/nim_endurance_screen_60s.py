#!/usr/bin/env python3
"""Bounded NVIDIA free-NIM endurance screen: 60s start-to-start, max 40 attempts.

Non-scientific. No retries. Stop on first 429. Does not print API keys.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiment1"))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.qualification_fixtures.nim_count_once import (
    NimProbeError,
    extract_prompt_tokens,
    load_api_key,
    post_chat_completions_once,
)

e0 = load_experiment0_config()
FX_DIR = REPO / "experiment0" / "qualification_fixtures"

# Predetermined rotation — large-context engineering fixtures only (no minimal).
FIXTURE_ROTATION = (
    "worst_case_actor",
    "worst_case_witness",
    "short_actor_t1",
    "short_witness",
    "multi_message_actor",
    "revision_shaped_actor",
)

MAX_ATTEMPTS = 40
TARGET_START_TO_START_SEC = 60.0
MODEL = "nvidia/nemotron-3-super-120b-a12b"


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


def load_probe_body(fixture_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = FX_DIR / f"{fixture_id}.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    body = fixture["provider_facing_request_body"]
    probe = {
        "model": body["model"],
        "messages": body["messages"],
        "max_tokens": 1,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    return fixture, probe


def main() -> int:
    run_id = datetime.now(timezone.utc).strftime("nim_endurance_%Y%m%dT%H%M%SZ")
    out_dir = REPO / "diagnostics" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    key = load_api_key(e0.NIM_API_KEY_ENV)
    attempts: list[dict[str, Any]] = []
    cumulative_input = 0
    cumulative_output = 0
    successes = 0
    t_wall0 = time.monotonic()
    next_sched = time.monotonic()
    stop_reason = "COMPLETED_40"
    classification = "NVIDIA_LARGE_INPUT_SCREEN_PASSED"

    meta = {
        "diagnostic": "nvidia_free_nim_endurance_screen_60s",
        "run_id": run_id,
        "model": MODEL,
        "base_url": e0.NIM_BASE_URL,
        "max_attempts": MAX_ATTEMPTS,
        "target_start_to_start_sec": TARGET_START_TO_START_SEC,
        "max_tokens": 1,
        "retries": 0,
        "fixture_rotation": list(FIXTURE_ROTATION),
        "scientific": False,
        "free_entitlement_note": (
            "Same integrate.api.nvidia.com NIM path used for prior free-tier "
            "Exp0/diagnostics; no paid provider configured. Account billing "
            "portal not queried; stop if charges are later discovered."
        ),
        "started_utc": _utc(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    for i in range(1, MAX_ATTEMPTS + 1):
        # Pace: wait until scheduled start; never overlap
        now = time.monotonic()
        if now < next_sched:
            time.sleep(next_sched - now)
        actual_start_mono = time.monotonic()
        scheduled_start_mono = next_sched
        # Next schedule is +60s from this actual start (start-to-start)
        next_sched = actual_start_mono + TARGET_START_TO_START_SEC

        fixture_id = FIXTURE_ROTATION[(i - 1) % len(FIXTURE_ROTATION)]
        fixture, probe = load_probe_body(fixture_id)
        inter = None
        if attempts:
            inter = actual_start_mono - attempts[-1]["_actual_start_mono"]

        rec: dict[str, Any] = {
            "attempt_index": i,
            "fixture_id": fixture_id,
            "fixture_body_sha256": fixture.get("provider_facing_request_body_sha256"),
            "fixture_local_prompt_tokens": fixture.get("local_prompt_tokens"),
            "scheduled_start_utc": _utc(),  # approx at wake
            "actual_start_utc": _utc(),
            "actual_inter_request_interval_sec": inter,
            "target_start_to_start_sec": TARGET_START_TO_START_SEC,
            "_actual_start_mono": actual_start_mono,
            "drift_from_schedule_sec": actual_start_mono - scheduled_start_mono,
        }
        print(
            f"[endurance] attempt={i}/{MAX_ATTEMPTS} fixture={fixture_id} "
            f"inter={inter}",
            flush=True,
        )

        t0 = time.monotonic()
        try:
            parsed = post_chat_completions_once(
                base_url=e0.NIM_BASE_URL,
                api_key=key,
                body=probe,
                timeout_sec=600.0,
            )
            pt, details = extract_prompt_tokens(parsed)
            dur = time.monotonic() - t0
            model_ret = details.get("model")
            if model_ret and model_ret != MODEL:
                rec.update(
                    {
                        "http_status": 200,
                        "duration_sec": dur,
                        "status": "FAIL_MODEL_MISMATCH",
                        "model_returned": model_ret,
                        "provider_prompt_tokens": pt,
                        "request_id": details.get("id"),
                    }
                )
                attempts.append(rec)
                stop_reason = "MODEL_MISMATCH"
                classification = "NVIDIA_ENDURANCE_SCREEN_FAILED"
                print("[endurance] STOP model mismatch", flush=True)
                break

            ptd = details.get("prompt_tokens_details") or {}
            cached = ptd.get("cached_tokens") if isinstance(ptd, dict) else None
            out_tok = details.get("completion_tokens") or 0
            cumulative_input += int(pt)
            cumulative_output += int(out_tok or 0)
            successes += 1
            rec.update(
                {
                    "http_status": 200,
                    "duration_sec": round(dur, 3),
                    "status": "OK",
                    "request_id": details.get("id"),
                    "input_tokens": pt,
                    "cached_tokens": cached,
                    "output_tokens": out_tok,
                    "model_returned": model_ret,
                    "finish_reason": details.get("finish_reason"),
                    "cumulative_accepted_input_tokens": cumulative_input,
                    "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
                }
            )
            attempts.append(rec)
            (out_dir / f"attempt_{i:02d}.json").write_text(
                json.dumps({k: v for k, v in rec.items() if not k.startswith("_")}, indent=2),
                encoding="utf-8",
            )
            print(
                f"[endurance] OK tokens={pt} cached={cached} dur={dur:.2f}s "
                f"cum_in={cumulative_input}",
                flush=True,
            )
        except NimProbeError as exc:
            dur = time.monotonic() - t0
            rec.update(
                {
                    "http_status": exc.status_code,
                    "duration_sec": round(dur, 3),
                    "status": "RATE_LIMITED" if exc.rate_limited else "PROVIDER_FAIL",
                    "rate_limited": bool(exc.rate_limited),
                    "error_redacted": _redact(str(exc))[:800],
                    "error_body_redacted": _redact(str(exc.raw)[:500]) if exc.raw else None,
                    "cumulative_accepted_input_tokens": cumulative_input,
                    "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
                }
            )
            attempts.append(rec)
            (out_dir / f"attempt_{i:02d}.json").write_text(
                json.dumps({k: v for k, v in rec.items() if not k.startswith("_")}, indent=2),
                encoding="utf-8",
            )
            stop_reason = "HTTP_429" if exc.rate_limited else "PROVIDER_FAIL"
            classification = "NVIDIA_ENDURANCE_SCREEN_FAILED"
            print(f"[endurance] STOP {stop_reason} status={exc.status_code}", flush=True)
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
                    "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
                }
            )
            attempts.append(rec)
            stop_reason = "UNEXPECTED"
            classification = "NVIDIA_ENDURANCE_SCREEN_FAILED"
            print(f"[endurance] STOP unexpected: {exc}", flush=True)
            break
    else:
        stop_reason = "COMPLETED_40"

    # Strip mono fields for summary
    clean = []
    for a in attempts:
        clean.append({k: v for k, v in a.items() if not k.startswith("_")})

    intervals = [
        a["actual_inter_request_interval_sec"]
        for a in clean
        if a.get("actual_inter_request_interval_sec") is not None
    ]
    summary = {
        **meta,
        "ended_utc": _utc(),
        "classification": classification,
        "stop_reason": stop_reason,
        "attempts_total": len(clean),
        "successes": successes,
        "failures": len(clean) - successes,
        "cumulative_accepted_input_tokens": cumulative_input,
        "cumulative_output_tokens": cumulative_output,
        "cumulative_wall_clock_sec": round(time.monotonic() - t_wall0, 3),
        "pacing": {
            "target_start_to_start_sec": TARGET_START_TO_START_SEC,
            "n_intervals": len(intervals),
            "min_interval_sec": min(intervals) if intervals else None,
            "max_interval_sec": max(intervals) if intervals else None,
            "mean_interval_sec": (sum(intervals) / len(intervals)) if intervals else None,
        },
        "first_failure": next((a for a in clean if a.get("status") != "OK"), None),
        "attempts": clean,
        "limits_of_inference": (
            "max_tokens=1 only; does not prove Exp0 Actor/Witness generation "
            "sustainability (~800/1600 output budgets, denser mid-episode pattern)."
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "classification": classification,
        "stop_reason": stop_reason,
        "attempts": len(clean),
        "successes": successes,
        "cum_input": cumulative_input,
        "out_dir": str(out_dir),
    }, indent=2), flush=True)
    return 0 if classification == "NVIDIA_LARGE_INPUT_SCREEN_PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
