#!/usr/bin/env python3
"""Independent 20s pacing diagnostic after cooldown from Phase-D 429.

Does NOT touch Experiment 0.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nim_large_context_rate_limit import (  # noqa: E402
    build_synthetic_content,
    one_shot_request,
    utc_now,
)

RUN_DIR = Path(__file__).resolve().parent / "runs" / "nim_rl_20261007T173827Z"
PHASE_D_429 = RUN_DIR / "phase_d_04.json"


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _hdr(headers: dict[str, str], *names: str) -> Any:
    lower = {k.lower(): v for k, v in headers.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def summarize(seq: int, r: dict[str, Any], interval: Optional[float]) -> dict[str, Any]:
    hdrs = r.get("response_headers") or {}
    rate = {
        k: v
        for k, v in hdrs.items()
        if any(t in k.lower() for t in ("rate", "retry", "quota", "limit", "remaining", "reset"))
    }
    return {
        "sequence": seq,
        "timestamp_utc_start": r.get("timestamp_utc_start"),
        "timestamp_utc_end": r.get("timestamp_utc_end"),
        "start_to_start_interval_sec": interval,
        "http_status": r.get("http_status"),
        "latency_ms": r.get("latency_ms"),
        "prompt_tokens": r.get("prompt_tokens"),
        "completion_tokens": r.get("completion_tokens"),
        "finish_reason": r.get("finish_reason"),
        "Nvcf-Reqid": _hdr(hdrs, "Nvcf-Reqid"),
        "Nvcf-Status": _hdr(hdrs, "Nvcf-Status"),
        "Retry-After": _hdr(hdrs, "Retry-After"),
        "rate_limit_and_quota_headers": rate,
        "all_response_headers": hdrs,
    }


def main() -> int:
    api_key = os.environ.get("NIM_API_KEY", "").strip()
    if not api_key:
        print("NIM_API_KEY is not set.", flush=True)
        return 2

    d429 = json.loads(PHASE_D_429.read_text(encoding="utf-8"))
    d429_end = _parse_utc(d429["timestamp_utc_end"])
    now = datetime.now(timezone.utc)
    elapsed = (now - d429_end).total_seconds()
    wait = max(0.0, 600.0 - elapsed)
    print(
        f"[cooldown] seconds_since_phase_d_429={elapsed:.1f} required>=600 wait={wait:.1f}",
        flush=True,
    )
    if wait > 0:
        time.sleep(wait)

    prior = json.loads((RUN_DIR / "report.json").read_text(encoding="utf-8"))
    content = build_synthetic_content(int(prior["phases"]["A"]["content_chars"]))
    print(f"[setup] content_chars={len(content)}", flush=True)

    # Pre-test
    print("[pretest] one ~170k request", flush=True)
    pretest = one_shot_request(api_key=api_key, content=content, max_tokens=1)
    (RUN_DIR / "phase_e_only_pretest.json").write_text(
        json.dumps(pretest, indent=2), encoding="utf-8"
    )
    pretest_sm = summarize(0, pretest, None)
    print(
        f"[pretest] status={pretest_sm['http_status']} pt={pretest_sm['prompt_tokens']} "
        f"latency_ms={pretest_sm['latency_ms']} Nvcf-Reqid={pretest_sm['Nvcf-Reqid']}",
        flush=True,
    )
    if pretest.get("http_status") == 429:
        report = {
            "verdict": "20S_TEST_BLOCKED_BY_EXISTING_THROTTLE",
            "pretest": pretest_sm,
            "generated_utc": utc_now(),
        }
        (RUN_DIR / "phase_e_only_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print("20S_TEST_BLOCKED_BY_EXISTING_THROTTLE", flush=True)
        return 3
    if pretest.get("http_status") != 200:
        print(f"PRETEST_FAILED status={pretest.get('http_status')}", flush=True)
        return 4

    # Respect start-to-start >=20s from pretest to E1
    time.sleep(20.0)

    spacing = 20.0
    count = 10
    summaries: list[dict[str, Any]] = []
    raws: list[dict[str, Any]] = []
    last_start_perf: Optional[float] = None
    last_start_utc: Optional[datetime] = None

    for i in range(count):
        if last_start_perf is not None:
            waited = time.perf_counter() - last_start_perf
            w = max(0.0, spacing - waited)
            if w > 0:
                print(f"[phase_e] waiting {w:.1f}s before request {i+1}", flush=True)
                time.sleep(w)
        last_start_perf = time.perf_counter()
        print(f"[phase_e] request {i+1}/{count} starting", flush=True)
        raw = one_shot_request(api_key=api_key, content=content, max_tokens=1)
        raw["phase_e_only_index"] = i + 1
        raws.append(raw)
        (RUN_DIR / f"phase_e_only_{i+1:02d}.json").write_text(
            json.dumps(raw, indent=2), encoding="utf-8"
        )
        start_utc = _parse_utc(raw["timestamp_utc_start"])
        interval = None
        if last_start_utc is not None:
            interval = (start_utc - last_start_utc).total_seconds()
        last_start_utc = start_utc
        sm = summarize(i + 1, raw, interval)
        summaries.append(sm)
        print(
            f"[phase_e] request {i+1} status={sm['http_status']} pt={sm['prompt_tokens']} "
            f"latency_ms={sm['latency_ms']} interval={interval} "
            f"Nvcf-Reqid={sm['Nvcf-Reqid']}",
            flush=True,
        )
        if raw.get("http_status") == 429:
            print("[phase_e] FIRST 429 — stop immediately", flush=True)
            break

    n_ok = sum(1 for s in summaries if s["http_status"] == 200)
    n_429 = sum(1 for s in summaries if s["http_status"] == 429)
    if n_429 == 0 and n_ok == 10:
        classification = "PHASE_E_20S_PACING_ALL_SUCCESS"
        result = "PASS"
    else:
        classification = "PHASE_E_20S_PACING_FAILED_ON_429"
        result = "FAIL"

    ok_tokens = sum(
        int(s["prompt_tokens"])
        for s in summaries
        if s["http_status"] == 200 and isinstance(s.get("prompt_tokens"), int)
    )

    # Header scan
    any_retry = any_rpm = any_tpm = any_rem = any_reset = False
    nvcf_ok = False
    for r in [pretest] + raws:
        for k, v in (r.get("response_headers") or {}).items():
            lk = k.lower()
            if lk == "retry-after" and v:
                any_retry = True
            if "rpm" in lk or ("ratelimit" in lk and "request" in lk):
                any_rpm = True
            if "tpm" in lk or ("ratelimit" in lk and "token" in lk):
                any_tpm = True
            if "remaining" in lk:
                any_rem = True
            if "reset" in lk:
                any_reset = True
            if lk == "nvcf-reqid" and v:
                nvcf_ok = True

    report = {
        "diagnostic": "nim_independent_20s_pacing_after_cooldown",
        "experiment0_frozen": {
            "run_id": "e0_20261007T132027Z",
            "status": "STOPPED_FOR_REVIEW",
            "completed": "19/60",
            "scientific_analysis": False,
        },
        "generated_utc": utc_now(),
        "cooldown_seconds_since_phase_d_429": elapsed if wait <= 0 else elapsed + wait,
        "pretest": pretest_sm,
        "result": result,
        "classification": classification,
        "successful_before_stop": n_ok,
        "approx_successful_prompt_tokens": ok_tokens,
        "requests": summaries,
        "comparison_table": {
            "Dense Exp0": "repeated 429",
            "15 s": "3 successes → 429",
            "20 s": classification,
            "30 s": "5/5 success",
            "60 s": "5/5 success",
        },
        "shortest_tested_interval_that_completed_entire_sequence_sec": (
            20 if result == "PASS" else 30
        ),
        "strength_of_evidence": {
            "20s_sequence_length": f"{n_ok + n_429}/10 attempted (target 10)",
            "30s_and_60s_prior_sequence_length": "5 requests each",
            "15s_prior_sequence_length": "stopped at 4 (3 success + 429)",
            "note": (
                "Evidence strength differs by design: 20s and 15s used sustained "
                "10-request targets; 30s/60s prior tests used 5-request sequences. "
                "A 10/10 success at 20s is stronger for that interval than a 5/5 "
                "at 30s for cross-interval comparison of robustness, but does not "
                "guarantee production safety. No unpublished NVIDIA TPM quota inferred."
            ),
        },
        "headers": {
            "Retry-After_exposed": any_retry,
            "RPM_exposed": any_rpm,
            "TPM_exposed": any_tpm,
            "remaining_quota_exposed": any_rem,
            "reset_time_exposed": any_reset,
            "NVCF_request_ID_exposed": nvcf_ok,
        },
        "do_not_resume_exp0": True,
    }

    out = RUN_DIR / "phase_e_only_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = RUN_DIR / "phase_e_only_report.md"
    md.write_text(_md(report), encoding="utf-8")
    print(classification, flush=True)
    print(f"Wrote {out}", flush=True)
    print(f"Wrote {md}", flush=True)
    return 0


def _md(r: dict[str, Any]) -> str:
    lines = [
        "# Independent 20-second NIM pacing diagnostic",
        "",
        f"Generated: `{r['generated_utc']}`",
        "",
        f"Classification: **{r['classification']}**",
        "",
        "## Pre-test",
        "",
        f"- status={r['pretest']['http_status']} pt={r['pretest']['prompt_tokens']} "
        f"latency_ms={r['pretest']['latency_ms']} Nvcf-Reqid={r['pretest']['Nvcf-Reqid']}",
        "",
        "## Requests",
        "",
        "| # | start UTC | interval | tokens | latency | HTTP | NVCF ID |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for req in r["requests"]:
        lines.append(
            f"| {req['sequence']} | {req['timestamp_utc_start']} | "
            f"{req['start_to_start_interval_sec']} | {req['prompt_tokens']} | "
            f"{req['latency_ms']} | {req['http_status']} | {req['Nvcf-Reqid']} |"
        )
    lines += [
        "",
        "## Comparison",
        "",
        "| Spacing | Sustained result |",
        "|---|---|",
    ]
    for k, v in r["comparison_table"].items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        f"**Shortest tested interval that completed its entire diagnostic sequence:** "
        f"**{r['shortest_tested_interval_that_completed_entire_sequence_sec']} s**",
        "",
        f"**Strength of evidence:** {r['strength_of_evidence']['note']}",
        "",
        f"Headers: {r['headers']}",
        "",
        "Experiment 0 was not resumed or modified.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
