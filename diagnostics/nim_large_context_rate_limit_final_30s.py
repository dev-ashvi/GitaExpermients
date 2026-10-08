#!/usr/bin/env python3
"""Final isolated 30s × 10-request NIM pacing validation.

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
PRIOR_429 = RUN_DIR / "phase_e_only_07.json"  # 20s diagnostic 429


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

    d429 = json.loads(PRIOR_429.read_text(encoding="utf-8"))
    end = _parse_utc(d429["timestamp_utc_end"])
    now = datetime.now(timezone.utc)
    elapsed = (now - end).total_seconds()
    wait = max(0.0, 600.0 - elapsed)
    print(
        f"[cooldown] seconds_since_20s_429={elapsed:.1f} required>=600 wait={wait:.1f}",
        flush=True,
    )
    if wait > 0:
        time.sleep(wait)

    prior = json.loads((RUN_DIR / "report.json").read_text(encoding="utf-8"))
    content = build_synthetic_content(int(prior["phases"]["A"]["content_chars"]))
    print(f"[setup] content_chars={len(content)}", flush=True)

    print("[pretest] one ~170k request", flush=True)
    pretest = one_shot_request(api_key=api_key, content=content, max_tokens=1)
    (RUN_DIR / "final_30s_pretest.json").write_text(
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
            "verdict": "FINAL_30S_VALIDATION_BLOCKED_BY_EXISTING_THROTTLE",
            "pretest": pretest_sm,
            "generated_utc": utc_now(),
        }
        (RUN_DIR / "final_30s_validation_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print("FINAL_30S_VALIDATION_BLOCKED_BY_EXISTING_THROTTLE", flush=True)
        return 3
    if pretest.get("http_status") != 200:
        print(f"PRETEST_FAILED status={pretest.get('http_status')}", flush=True)
        return 4

    time.sleep(30.0)  # start-to-start from pretest

    spacing = 30.0
    count = 10
    summaries: list[dict[str, Any]] = []
    last_start_perf: Optional[float] = None
    last_start_utc: Optional[datetime] = None

    for i in range(count):
        if last_start_perf is not None:
            waited = time.perf_counter() - last_start_perf
            w = max(0.0, spacing - waited)
            if w > 0:
                print(f"[final_30s] waiting {w:.1f}s before request {i+1}", flush=True)
                time.sleep(w)
        last_start_perf = time.perf_counter()
        print(f"[final_30s] request {i+1}/{count} starting", flush=True)
        raw = one_shot_request(api_key=api_key, content=content, max_tokens=1)
        raw["final_30s_index"] = i + 1
        (RUN_DIR / f"final_30s_{i+1:02d}.json").write_text(
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
            f"[final_30s] request {i+1} status={sm['http_status']} pt={sm['prompt_tokens']} "
            f"latency_ms={sm['latency_ms']} interval={interval} "
            f"Nvcf-Reqid={sm['Nvcf-Reqid']}",
            flush=True,
        )
        if raw.get("http_status") == 429:
            print("[final_30s] FIRST 429 — stop immediately", flush=True)
            break

    n_ok = sum(1 for s in summaries if s["http_status"] == 200)
    n_429 = sum(1 for s in summaries if s["http_status"] == 429)
    if n_429 == 0 and n_ok == 10:
        classification = "FINAL_30S_VALIDATION_PASS_10_OF_10"
        result = "PASS"
    else:
        classification = "FINAL_30S_VALIDATION_FAILED_ON_429"
        result = "FAIL"

    ok_tokens = sum(
        int(s["prompt_tokens"])
        for s in summaries
        if s["http_status"] == 200 and isinstance(s.get("prompt_tokens"), int)
    )

    report = {
        "diagnostic": "final_30s_sustained_validation_10_requests",
        "experiment0_frozen": {
            "run_id": "e0_20261007T132027Z",
            "status": "STOPPED_FOR_REVIEW",
            "completed": "19/60",
            "scientific_analysis": False,
        },
        "generated_utc": utc_now(),
        "pretest": pretest_sm,
        "result": result,
        "classification": classification,
        "successful_before_stop": n_ok,
        "approx_successful_prompt_tokens": ok_tokens,
        "requests": summaries,
        "evidence_table": {
            "Dense Exp0": "repeated 429",
            "15 s": "3 successes → 429",
            "20 s": "6 successes → 429",
            "30 s initial": "5/5 success",
            "30 s sustained": classification,
            "60 s": "5/5 success",
        },
        "no_unpublished_tpm_quota_inferred": True,
        "do_not_resume_exp0": True,
        "no_further_pacing_exploration": True,
    }

    out = RUN_DIR / "final_30s_validation_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = RUN_DIR / "final_30s_validation_report.md"
    lines = [
        "# Final 30-second sustained NIM pacing validation",
        "",
        f"Generated: `{report['generated_utc']}`",
        "",
        f"**{classification}**",
        "",
        f"Pre-test: status={pretest_sm['http_status']} pt={pretest_sm['prompt_tokens']} "
        f"Nvcf-Reqid={pretest_sm['Nvcf-Reqid']}",
        "",
        "| # | start UTC | interval | tokens | latency | HTTP | NVCF ID |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for req in summaries:
        lines.append(
            f"| {req['sequence']} | {req['timestamp_utc_start']} | "
            f"{req['start_to_start_interval_sec']} | {req['prompt_tokens']} | "
            f"{req['latency_ms']} | {req['http_status']} | {req['Nvcf-Reqid']} |"
        )
    lines += [
        "",
        "| Spacing | Result |",
        "|---|---|",
    ]
    for k, v in report["evidence_table"].items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "Experiment 0 was not resumed or modified. No further pacing intervals tested.",
        "",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")
    print(classification, flush=True)
    print(f"Wrote {out}", flush=True)
    print(f"Wrote {md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
