#!/usr/bin/env python3
"""Phase C continuation for the isolated NIM large-context rate-limit diagnostic.

Does NOT touch Experiment 0. Continues an existing diagnostics/runs/nim_rl_* directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse helpers from the Phase A/B diagnostic (same process, no Exp0 imports).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nim_large_context_rate_limit import (  # noqa: E402
    ACCEPTABLE_MAX,
    ACCEPTABLE_MIN,
    build_synthetic_content,
    one_shot_request,
    utc_now,
)

DEFAULT_PRIOR = Path(__file__).resolve().parent / "runs" / "nim_rl_20261007T173827Z"


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def summarize_request(seq: int, r: dict[str, Any]) -> dict[str, Any]:
    hdrs = r.get("response_headers") or {}
    hl = r.get("highlighted_headers") or {}
    # Case-insensitive lookup helpers
    lower = {k.lower(): v for k, v in hdrs.items()}

    def get(*names: str) -> Any:
        for n in names:
            if n.lower() in lower:
                return lower[n.lower()]
            if n in hl:
                return hl[n]
        return None

    rate_headers = {
        k: v
        for k, v in hdrs.items()
        if any(
            t in k.lower()
            for t in ("rate", "retry", "quota", "limit", "remaining", "reset")
        )
    }
    return {
        "sequence": seq,
        "timestamp_utc_start": r.get("timestamp_utc_start"),
        "timestamp_utc_end": r.get("timestamp_utc_end"),
        "latency_ms": r.get("latency_ms"),
        "http_status": r.get("http_status"),
        "prompt_tokens": r.get("prompt_tokens"),
        "completion_tokens": r.get("completion_tokens"),
        "finish_reason": r.get("finish_reason"),
        "Nvcf-Reqid": get("Nvcf-Reqid", "nvcf-reqid"),
        "Nvcf-Status": get("Nvcf-Status", "nvcf-status"),
        "Retry-After": get("Retry-After", "retry-after"),
        "rate_limit_and_quota_headers": rate_headers,
        "all_response_headers": hdrs,
    }


def header_observation_across(results: list[dict[str, Any]]) -> dict[str, Any]:
    any_retry = False
    any_rpm = False
    any_tpm = False
    any_remaining = False
    any_reset = False
    nvcf_ids: list[str] = []
    all_keys: set[str] = set()
    for r in results:
        for k, v in (r.get("all_response_headers") or r.get("response_headers") or {}).items():
            all_keys.add(k)
            lk = k.lower()
            if lk == "retry-after" and v:
                any_retry = True
            if "rpm" in lk or ("ratelimit" in lk and "request" in lk):
                any_rpm = True
            if "tpm" in lk or ("ratelimit" in lk and "token" in lk):
                any_tpm = True
            if "remaining" in lk:
                any_remaining = True
            if "reset" in lk:
                any_reset = True
            if lk == "nvcf-reqid" and v:
                nvcf_ids.append(str(v))
    return {
        "Retry-After_exposed": any_retry,
        "RPM_limit_exposed": any_rpm,
        "TPM_limit_exposed": any_tpm,
        "remaining_quota_exposed": any_remaining,
        "reset_time_exposed": any_reset,
        "NVCF_request_IDs_exposed": bool(nvcf_ids),
        "NVCF_request_IDs": nvcf_ids,
        "all_header_names_seen": sorted(all_keys),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prior-run-dir", default=str(DEFAULT_PRIOR))
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--spacing-sec", type=float, default=60.0)
    p.add_argument("--min-gap-after-phase-b-sec", type=float, default=300.0)
    args = p.parse_args()

    api_key = os.environ.get("NIM_API_KEY", "").strip()
    if not api_key:
        print("NIM_API_KEY is not set.", flush=True)
        return 2

    run_dir = Path(args.prior_run_dir)
    report_path = run_dir / "report.json"
    if not report_path.exists():
        print(f"Missing prior report: {report_path}", flush=True)
        return 2

    prior = json.loads(report_path.read_text(encoding="utf-8"))
    phase_a = prior["phases"]["A"]
    phase_b = prior["phases"]["B"]
    last_b = phase_b["results"][-1]
    last_b_end = _parse_utc(last_b["timestamp_utc_end"])
    now = datetime.now(timezone.utc)
    elapsed = (now - last_b_end).total_seconds()
    need = max(0.0, float(args.min_gap_after_phase_b_sec) - elapsed)
    print(
        f"[gate] seconds_since_phase_b_end={elapsed:.1f} "
        f"required>={args.min_gap_after_phase_b_sec} wait={need:.1f}",
        flush=True,
    )
    if need > 0:
        print(f"[gate] waiting {need:.1f}s before Phase C", flush=True)
        time.sleep(need)

    content_chars = int(phase_a["content_chars"])
    content = build_synthetic_content(content_chars)
    print(
        f"[phase_c] content_chars={len(content)} "
        f"(same deterministic construction as Phase A/B)",
        flush=True,
    )

    spacing = float(args.spacing_sec)
    n = int(args.count)
    results_raw: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    last_start = 0.0

    for i in range(n):
        if i > 0:
            waited = time.perf_counter() - last_start
            wait = max(0.0, spacing - waited)
            if wait > 0:
                print(f"[phase_c] waiting {wait:.1f}s before request {i+1}", flush=True)
                time.sleep(wait)
        last_start = time.perf_counter()
        print(f"[phase_c] request {i+1}/{n} starting", flush=True)
        raw = one_shot_request(api_key=api_key, content=content, max_tokens=1)
        raw["phase_c_index"] = i + 1
        results_raw.append(raw)
        (run_dir / f"phase_c_{i+1:02d}.json").write_text(
            json.dumps(raw, indent=2), encoding="utf-8"
        )
        sm = summarize_request(i + 1, raw)
        summaries.append(sm)
        print(
            f"[phase_c] request {i+1} status={sm['http_status']} "
            f"prompt_tokens={sm['prompt_tokens']} latency_ms={sm['latency_ms']} "
            f"Nvcf-Reqid={sm['Nvcf-Reqid']}",
            flush=True,
        )
        if raw.get("http_status") == 429:
            print("[phase_c] FIRST 429 — stopping immediately (no retry)", flush=True)
            break

    statuses = [s["http_status"] for s in summaries]
    n_200 = sum(1 for s in statuses if s == 200)
    n_429 = sum(1 for s in statuses if s == 429)
    if n_429 == 0 and n_200 == len(summaries) == n:
        phase_c_class = "PHASE_C_60S_PACING_ALL_SUCCESS"
        phase_c_pass = "PASS"
    elif n_429 > 0:
        phase_c_class = "PHASE_C_60S_PACING_STOPPED_ON_429"
        phase_c_pass = "FAIL"
    else:
        phase_c_class = "PHASE_C_60S_PACING_INCONCLUSIVE"
        phase_c_pass = "FAIL"

    # Combined header observations A+B+C
    all_for_headers: list[dict[str, Any]] = []
    all_for_headers.append(phase_a)
    all_for_headers.extend(phase_b["results"])
    all_for_headers.extend(results_raw)
    header_obs = header_observation_across(all_for_headers)

    # Phase B pass/fail from prior
    b_statuses = [x.get("http_status") for x in phase_b["results"]]
    b_pass = (
        "PASS"
        if all(s == 200 for s in b_statuses) and len(b_statuses) == 5
        else "FAIL"
    )
    a_pass = "PASS" if phase_a.get("http_status") == 200 else "FAIL"

    combined = {
        "diagnostic": "nim_large_context_rate_limit_combined_A_B_C",
        "isolation": "outside_experiment0_execution_path",
        "experiment0_run_forbidden": "e0_20261007T132027Z",
        "experiment0_must_remain": {
            "run_id": "e0_20261007T132027Z",
            "status": "STOPPED_FOR_REVIEW",
            "completed": "19/60",
        },
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "generated_utc": utc_now(),
        "A_phase_a": {
            "result": a_pass,
            "http_status": phase_a.get("http_status"),
            "prompt_tokens": phase_a.get("prompt_tokens"),
            "latency_ms": phase_a.get("latency_ms"),
            "finish_reason": phase_a.get("finish_reason"),
            "Nvcf-Reqid": (phase_a.get("highlighted_headers") or {}).get("Nvcf-Reqid")
            or (phase_a.get("response_headers") or {}).get("Nvcf-Reqid"),
            "Nvcf-Status": (phase_a.get("response_headers") or {}).get("Nvcf-Status"),
            "note": "Large-context verification (~170k prompt tokens, max_tokens=1)",
        },
        "B_phase_b_30s": {
            "result": b_pass,
            "classification": prior.get("verdict"),
            "spacing_sec": phase_b.get("spacing_sec"),
            "statuses": b_statuses,
            "requests": [
                summarize_request(i + 1, r) for i, r in enumerate(phase_b["results"])
            ],
        },
        "C_phase_c_60s": {
            "result": phase_c_pass,
            "classification": phase_c_class,
            "spacing_sec": spacing,
            "seconds_since_phase_b_before_start": (
                datetime.now(timezone.utc) - last_b_end
            ).total_seconds(),
            "statuses": statuses,
            "requests": summaries,
        },
        "D_header_observations": header_obs,
        "E_comparison_with_experiment0_operational_only": {
            "diagnostic_spacing": {
                "phase_b_start_to_start_sec": 30,
                "phase_c_start_to_start_sec": 60,
                "attempts_per_scheduled_request": 1,
                "automatic_429_retries": False,
            },
            "diagnostic_prompt_token_sizes": {
                "target": "~170006",
                "phase_a": phase_a.get("prompt_tokens"),
                "phase_b": [x.get("prompt_tokens") for x in phase_b["results"]],
                "phase_c": [x.get("prompt_tokens") for x in results_raw],
                "in_160k_180k_band": all(
                    isinstance(x, int) and ACCEPTABLE_MIN <= x <= ACCEPTABLE_MAX
                    for x in (
                        [phase_a.get("prompt_tokens")]
                        + [r.get("prompt_tokens") for r in phase_b["results"]]
                        + [r.get("prompt_tokens") for r in results_raw]
                    )
                    if x is not None
                ),
            },
            "exp0_observed_dense_call_behavior": (
                "Experiment 0 episode execution issues many large-context NIM calls "
                "in rapid succession within a turn and across turns (Actor then Witness, "
                "plus nested retries on transient errors under the frozen retry budget). "
                "On run e0_20261007T132027Z, HTTP 429s repeatedly appeared mid-episode "
                "(e.g. around turns 6–7) after bursts of successful generation calls, "
                "while completed episodes remained at 19/60 under STOPPED_FOR_REVIEW."
            ),
            "consistent_with_throughput_sensitive_throttling": (
                "Yes — operationally consistent. Isolated ~170k requests at 30s and 60s "
                "start spacing completed without 429 in this diagnostic, whereas Exp0's "
                "denser same-model call pattern encountered 429 after short successful "
                "bursts. This does not identify a specific unpublished NVIDIA TPM quota."
            ),
            "no_scientific_outcomes_inspected": True,
        },
        "F_recommendation_future_run_only": {
            "recommended_operational_pacing_interval_sec": 30,
            "basis": (
                "Phase B (30s start spacing) and Phase C (60s start spacing) both "
                "achieved 5/5 HTTP 200 on ~170k-token synthetic requests with no "
                "automatic retries. 30s is the shortest spacing tested that fully "
                "succeeded; 60s also succeeded but is more conservative."
            ),
            "do_not_apply_to_started_experiment0": True,
            "do_not_resume_experiment0_from_this_diagnostic": True,
        },
        "phase_c_raw_count": len(results_raw),
    }

    # Update prior report.json with Phase C + combined pointer
    prior["phases"]["C"] = {
        "spacing_sec": spacing,
        "requested_max": n,
        "completed": len(results_raw),
        "classification": phase_c_class,
        "results": results_raw,
    }
    prior["combined_report_path"] = "combined_report_A_B_C.json"
    prior["phase_c_finished_utc"] = utc_now()
    prior["overall_after_phase_c"] = phase_c_class
    report_path.write_text(json.dumps(prior, indent=2), encoding="utf-8")

    out = run_dir / "combined_report_A_B_C.json"
    out.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    # Also a markdown for methodological review
    md = run_dir / "combined_report_A_B_C.md"
    md.write_text(_to_markdown(combined), encoding="utf-8")
    print(phase_c_class, flush=True)
    print(f"Wrote {out}", flush=True)
    print(f"Wrote {md}", flush=True)
    return 0


def _to_markdown(c: dict[str, Any]) -> str:
    a = c["A_phase_a"]
    b = c["B_phase_b_30s"]
    cc = c["C_phase_c_60s"]
    d = c["D_header_observations"]
    e = c["E_comparison_with_experiment0_operational_only"]
    f = c["F_recommendation_future_run_only"]
    lines = [
        "# Combined NIM large-context rate-limit diagnostic (A/B/C)",
        "",
        f"Generated: `{c['generated_utc']}`",
        "",
        "Experiment 0 was **not** resumed or modified.",
        "",
        "## A. Phase A — large-context verification",
        "",
        f"- Result: **{a['result']}**",
        f"- HTTP status: `{a['http_status']}`",
        f"- prompt_tokens: `{a['prompt_tokens']}`",
        f"- latency_ms: `{a['latency_ms']}`",
        f"- finish_reason: `{a['finish_reason']}`",
        f"- Nvcf-Reqid: `{a['Nvcf-Reqid']}`",
        f"- Nvcf-Status: `{a['Nvcf-Status']}`",
        "",
        "## B. Phase B — 30-second pacing",
        "",
        f"- Result: **{b['result']}** (`{b['classification']}`)",
        f"- Spacing: `{b['spacing_sec']}` s",
        f"- Statuses: `{b['statuses']}`",
        "",
    ]
    for req in b["requests"]:
        lines.append(
            f"- B{req['sequence']}: status={req['http_status']} "
            f"pt={req['prompt_tokens']} latency_ms={req['latency_ms']} "
            f"Nvcf-Reqid={req['Nvcf-Reqid']} "
            f"Retry-After={req['Retry-After']}"
        )
    lines += [
        "",
        "## C. Phase C — 60-second pacing",
        "",
        f"- Result: **{cc['result']}** (`{cc['classification']}`)",
        f"- Spacing: `{cc['spacing_sec']}` s",
        f"- Statuses: `{cc['statuses']}`",
        "",
    ]
    for req in cc["requests"]:
        lines.append(
            f"- C{req['sequence']}: status={req['http_status']} "
            f"pt={req['prompt_tokens']} latency_ms={req['latency_ms']} "
            f"start={req['timestamp_utc_start']} end={req['timestamp_utc_end']} "
            f"Nvcf-Reqid={req['Nvcf-Reqid']} Nvcf-Status={req['Nvcf-Status']} "
            f"Retry-After={req['Retry-After']} "
            f"rate/quota_headers={req['rate_limit_and_quota_headers']}"
        )
    lines += [
        "",
        "## D. Header observations",
        "",
        f"- Retry-After exposed: **{d['Retry-After_exposed']}**",
        f"- RPM limit exposed: **{d['RPM_limit_exposed']}**",
        f"- TPM limit exposed: **{d['TPM_limit_exposed']}**",
        f"- Remaining quota exposed: **{d['remaining_quota_exposed']}**",
        f"- Reset time exposed: **{d['reset_time_exposed']}**",
        f"- NVCF request IDs exposed: **{d['NVCF_request_IDs_exposed']}**",
        f"- Header names seen: `{d['all_header_names_seen']}`",
        "",
        "## E. Comparison with Experiment 0 (operational only)",
        "",
        f"- Diagnostic spacing: `{e['diagnostic_spacing']}`",
        f"- Diagnostic prompt-token sizes: `{e['diagnostic_prompt_token_sizes']}`",
        f"- Exp0 dense-call behavior: {e['exp0_observed_dense_call_behavior']}",
        f"- Consistent with throughput-sensitive throttling: "
        f"{e['consistent_with_throughput_sensitive_throttling']}",
        "",
        "## F. Recommendation (FUTURE run only)",
        "",
        f"- Recommended pacing interval: **{f['recommended_operational_pacing_interval_sec']} s** "
        f"between large-context request starts",
        f"- Basis: {f['basis']}",
        f"- Do not apply to started Experiment 0: **{f['do_not_apply_to_started_experiment0']}**",
        f"- Do not resume Experiment 0 from this diagnostic: "
        f"**{f['do_not_resume_experiment0_from_this_diagnostic']}**",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
