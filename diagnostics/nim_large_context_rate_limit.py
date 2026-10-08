#!/usr/bin/env python3
"""Standalone NVIDIA NIM large-context rate-limit diagnostic.

NOT part of Alignment Experiment 0. Does not read/write Exp0 run artifacts,
prompts, sources, or execution code paths.

Each scheduled request is a single HTTP attempt (no automatic 429 retries).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MODEL = "nvidia/nemotron-3-super-120b-a12b"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
TARGET_PROMPT_TOKENS = 170_000
ACCEPTABLE_MIN = 160_000
ACCEPTABLE_MAX = 180_000
# Conservative chars/token for synthetic padding (slightly overshoot then trim via probe).
CHARS_PER_TOKEN_GUESS = 3.2
UNIT = (
    "SYNTHETIC_DIAGNOSTIC_PAD_BLOCK_0001 "
    "abcdefghijklmnopqrstuvwxyz0123456789 "
    "THE_QUICK_BROWN_FOX_JUMPS_OVER_THE_LAZY_DOG "
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in ("authorization", "cookie", "set-cookie") or "nvapi-" in str(v).lower():
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


def highlight_rate_headers(headers: dict[str, str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if any(
            tok in lk
            for tok in (
                "rate",
                "retry",
                "quota",
                "limit",
                "remaining",
                "reset",
                "reqid",
                "request-id",
                "nvcf",
            )
        ):
            found[k] = v
    return found


def build_synthetic_content(approx_chars: int) -> str:
    """Deterministic repeated synthetic text (no Exp0 content)."""
    if approx_chars <= 0:
        return "ping"
    reps = (approx_chars // len(UNIT)) + 2
    blob = UNIT * reps
    return blob[:approx_chars]


def one_shot_request(
    *,
    api_key: str,
    content: str,
    max_tokens: int = 1,
    timeout_sec: float = 600.0,
) -> dict[str, Any]:
    """Single HTTP attempt. No retries."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    started = utc_now()
    t0 = time.perf_counter()
    status: int
    raw: str
    headers: dict[str, str]
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            raw = resp.read().decode("utf-8", errors="replace")
            headers = {k: v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        status = int(e.code)
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        headers = {k: v for k, v in (e.headers.items() if e.headers else [])}
    except Exception as exc:  # noqa: BLE001
        return {
            "timestamp_utc_start": started,
            "timestamp_utc_end": utc_now(),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "http_status": None,
            "error": type(exc).__name__ + ": " + str(exc)[:500],
            "response_headers": {},
            "highlighted_headers": {},
            "response_body_preview": "",
        }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    ended = utc_now()
    safe_headers = redact_headers(headers)
    parsed: Any = None
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = None

    usage = (parsed or {}).get("usage") if isinstance(parsed, dict) else None
    choices = (parsed or {}).get("choices") if isinstance(parsed, dict) else None
    finish = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        finish = choices[0].get("finish_reason")

    body_preview = raw[:1500]
    if "nvapi-" in body_preview.lower():
        body_preview = "[REDACTED: contained credential-like material]"

    return {
        "timestamp_utc_start": started,
        "timestamp_utc_end": ended,
        "latency_ms": latency_ms,
        "http_status": status,
        "prompt_tokens": (usage or {}).get("prompt_tokens") if isinstance(usage, dict) else None,
        "completion_tokens": (usage or {}).get("completion_tokens")
        if isinstance(usage, dict)
        else None,
        "total_tokens": (usage or {}).get("total_tokens") if isinstance(usage, dict) else None,
        "finish_reason": finish,
        "model_returned": (parsed or {}).get("model") if isinstance(parsed, dict) else None,
        "response_id": (parsed or {}).get("id") if isinstance(parsed, dict) else None,
        "response_headers": safe_headers,
        "highlighted_headers": highlight_rate_headers(safe_headers),
        "response_body_preview": body_preview,
        "content_chars": len(content),
    }


def calibrate_content(api_key: str, out_dir: Path) -> tuple[str, dict[str, Any]]:
    """Build synthetic content whose provider prompt_tokens ~170k."""
    # Start from guess; one calibration request with max_tokens=1.
    guess_chars = int(TARGET_PROMPT_TOKENS * CHARS_PER_TOKEN_GUESS)
    content = build_synthetic_content(guess_chars)
    print(f"[calibrate] sending size probe chars={len(content)}", flush=True)
    probe = one_shot_request(api_key=api_key, content=content, max_tokens=1)
    (out_dir / "phase_calibrate_probe.json").write_text(
        json.dumps(probe, indent=2), encoding="utf-8"
    )
    if probe.get("http_status") == 429:
        return content, probe
    if probe.get("http_status") != 200 or not probe.get("prompt_tokens"):
        return content, probe

    pt = int(probe["prompt_tokens"])
    if ACCEPTABLE_MIN <= pt <= ACCEPTABLE_MAX:
        print(f"[calibrate] in range prompt_tokens={pt}", flush=True)
        return content, probe

    # Rescale deterministically and re-probe once.
    scale = TARGET_PROMPT_TOKENS / max(pt, 1)
    new_chars = max(1000, int(len(content) * scale))
    content2 = build_synthetic_content(new_chars)
    print(
        f"[calibrate] rescale chars {len(content)} -> {len(content2)} "
        f"(observed_pt={pt})",
        flush=True,
    )
    probe2 = one_shot_request(api_key=api_key, content=content2, max_tokens=1)
    (out_dir / "phase_calibrate_probe2.json").write_text(
        json.dumps(probe2, indent=2), encoding="utf-8"
    )
    return content2, probe2


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NIM large-context rate-limit diagnostic")
    parser.add_argument(
        "--out-dir",
        default="",
        help="Output directory (default: diagnostics/runs/<timestamp>)",
    )
    parser.add_argument("--phase-b-count", type=int, default=5)
    parser.add_argument("--phase-b-spacing-sec", type=float, default=30.0)
    args = parser.parse_args(argv)

    api_key = os.environ.get("NIM_API_KEY", "").strip()
    if not api_key:
        print("NIM_API_KEY is not set in the environment.", flush=True)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir) if args.out_dir else (
        Path(__file__).resolve().parent / "runs" / f"nim_rl_{stamp}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "diagnostic": "nim_large_context_rate_limit",
        "isolation": "outside_experiment0_execution_path",
        "experiment0_run_forbidden": "e0_20261007T132027Z",
        "model": MODEL,
        "endpoint": ENDPOINT,
        "enable_thinking": False,
        "max_tokens": 1,
        "no_automatic_retries": True,
        "started_utc": utc_now(),
        "phases": {},
    }

    # ── Calibration / Phase A content ─────────────────────────────────────
    content, cal = calibrate_content(api_key, out_dir)
    report["phases"]["calibrate"] = {
        "content_chars": len(content),
        "last_probe": {
            k: cal.get(k)
            for k in (
                "http_status",
                "prompt_tokens",
                "latency_ms",
                "highlighted_headers",
                "error",
            )
        },
    }

    # If calibration itself was a successful ~170k call, treat it as Phase A
    # when already in range; otherwise send dedicated Phase A.
    cal_pt = cal.get("prompt_tokens")
    cal_status = cal.get("http_status")

    if cal_status == 429:
        report["verdict"] = "LARGE_CONTEXT_CURRENTLY_THROTTLED"
        report["phase_a"] = cal
        report["stopped_utc"] = utc_now()
        (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("LARGE_CONTEXT_CURRENTLY_THROTTLED", flush=True)
        print(f"Wrote {out_dir / 'report.json'}", flush=True)
        return 3

    phase_a: dict[str, Any]
    if (
        cal_status == 200
        and isinstance(cal_pt, int)
        and ACCEPTABLE_MIN <= cal_pt <= ACCEPTABLE_MAX
    ):
        # Last calibrate probe already satisfies Phase A size + success.
        phase_a = dict(cal)
        phase_a["note"] = "phase_a_satisfied_by_final_calibration_probe"
        print(
            f"[phase_a] reused calibration probe status=200 prompt_tokens={cal_pt}",
            flush=True,
        )
    else:
        print("[phase_a] sending dedicated large-context request", flush=True)
        # Ensure spacing from calibration if we just probed.
        time.sleep(2.0)
        phase_a = one_shot_request(api_key=api_key, content=content, max_tokens=1)

    (out_dir / "phase_a.json").write_text(json.dumps(phase_a, indent=2), encoding="utf-8")
    report["phases"]["A"] = phase_a

    if phase_a.get("http_status") == 429:
        report["verdict"] = "LARGE_CONTEXT_CURRENTLY_THROTTLED"
        report["stopped_utc"] = utc_now()
        (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("LARGE_CONTEXT_CURRENTLY_THROTTLED", flush=True)
        print(f"Wrote {out_dir / 'report.json'}", flush=True)
        return 3

    if phase_a.get("http_status") != 200:
        report["verdict"] = "PHASE_A_FAILED_NON_429"
        report["stopped_utc"] = utc_now()
        (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"PHASE_A_FAILED status={phase_a.get('http_status')}", flush=True)
        return 4

    pt = phase_a.get("prompt_tokens")
    print(
        f"[phase_a] OK status=200 prompt_tokens={pt} latency_ms={phase_a.get('latency_ms')}",
        flush=True,
    )

    # ── Phase B: <=5 requests, starts >=30s apart ─────────────────────────
    phase_b_results: list[dict[str, Any]] = []
    spacing = float(args.phase_b_spacing_sec)
    n_b = int(args.phase_b_count)
    print(f"[phase_b] up to {n_b} requests, start spacing >= {spacing}s, no retries", flush=True)

    last_start = time.perf_counter()
    # Phase A already consumed a large call; wait full spacing before B1.
    time.sleep(spacing)

    for i in range(n_b):
        if i > 0:
            elapsed = time.perf_counter() - last_start
            wait = max(0.0, spacing - elapsed)
            if wait > 0:
                print(f"[phase_b] waiting {wait:.1f}s before request {i+1}", flush=True)
                time.sleep(wait)
        last_start = time.perf_counter()
        print(f"[phase_b] request {i+1}/{n_b} starting", flush=True)
        result = one_shot_request(api_key=api_key, content=content, max_tokens=1)
        result["phase_b_index"] = i + 1
        phase_b_results.append(result)
        (out_dir / f"phase_b_{i+1:02d}.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(
            f"[phase_b] request {i+1} status={result.get('http_status')} "
            f"prompt_tokens={result.get('prompt_tokens')} "
            f"latency_ms={result.get('latency_ms')}",
            flush=True,
        )
        if result.get("http_status") == 429:
            print("[phase_b] first 429 observed — stopping further paced requests", flush=True)
            break

    report["phases"]["B"] = {
        "spacing_sec": spacing,
        "requested_max": n_b,
        "completed": len(phase_b_results),
        "results": phase_b_results,
    }

    statuses = [r.get("http_status") for r in phase_b_results]
    n_200 = sum(1 for s in statuses if s == 200)
    n_429 = sum(1 for s in statuses if s == 429)
    if n_429 == 0 and n_200 == len(phase_b_results) and phase_b_results:
        verdict = "PHASE_B_30S_PACING_ALL_SUCCESS"
    elif n_429 > 0 and n_200 > 0:
        verdict = "PHASE_B_30S_PACING_PARTIAL_THROTTLE"
    elif n_429 > 0 and n_200 == 0:
        verdict = "PHASE_B_30S_PACING_IMMEDIATE_THROTTLE"
    else:
        verdict = "PHASE_B_INCONCLUSIVE"

    report["verdict"] = verdict
    report["summary"] = {
        "phase_a_status": phase_a.get("http_status"),
        "phase_a_prompt_tokens": phase_a.get("prompt_tokens"),
        "phase_b_statuses": statuses,
        "phase_b_successes": n_200,
        "phase_b_429s": n_429,
    }
    report["finished_utc"] = utc_now()
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(verdict, flush=True)
    print(f"Wrote {out_dir / 'report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
