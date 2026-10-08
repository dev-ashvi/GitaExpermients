#!/usr/bin/env python3
"""Phases D (15s) and E (20s) for isolated NIM large-context pacing diagnostic.

Does NOT touch Experiment 0. Caps at 1 pre-test + 10 D + 10 E = 21 large requests.
"""

from __future__ import annotations

import argparse
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

DEFAULT_PRIOR = Path(__file__).resolve().parent / "runs" / "nim_rl_20261007T173827Z"


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _hdr(headers: dict[str, str], *names: str) -> Any:
    lower = {k.lower(): v for k, v in headers.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def summarize(seq: int, r: dict[str, Any], start_interval_sec: Optional[float]) -> dict[str, Any]:
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
        "start_to_start_interval_sec": start_interval_sec,
        "latency_ms": r.get("latency_ms"),
        "http_status": r.get("http_status"),
        "prompt_tokens": r.get("prompt_tokens"),
        "completion_tokens": r.get("completion_tokens"),
        "finish_reason": r.get("finish_reason"),
        "Nvcf-Reqid": _hdr(hdrs, "Nvcf-Reqid"),
        "Nvcf-Status": _hdr(hdrs, "Nvcf-Status"),
        "Retry-After": _hdr(hdrs, "Retry-After"),
        "rate_limit_and_quota_headers": rate,
        "all_response_headers": hdrs,
    }


def header_obs(results: list[dict[str, Any]]) -> dict[str, Any]:
    any_retry = any_rpm = any_tpm = any_rem = any_reset = False
    nvcf: list[str] = []
    names: set[str] = set()
    for r in results:
        hdrs = r.get("all_response_headers") or r.get("response_headers") or {}
        for k, v in hdrs.items():
            names.add(k)
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
                nvcf.append(str(v))
    return {
        "Retry-After_exposed": any_retry,
        "RPM_limit_exposed": any_rpm,
        "TPM_limit_exposed": any_tpm,
        "remaining_quota_exposed": any_rem,
        "reset_time_exposed": any_reset,
        "NVCF_request_IDs_exposed": bool(nvcf),
        "NVCF_request_IDs": nvcf,
        "all_header_names_seen": sorted(names),
    }


def paced_phase(
    *,
    api_key: str,
    content: str,
    count: int,
    spacing_sec: float,
    run_dir: Path,
    phase_letter: str,
) -> dict[str, Any]:
    raws: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    last_start_perf: Optional[float] = None
    last_start_utc: Optional[datetime] = None
    phase_t0 = time.perf_counter()

    for i in range(count):
        if last_start_perf is not None:
            waited = time.perf_counter() - last_start_perf
            wait = max(0.0, spacing_sec - waited)
            if wait > 0:
                print(
                    f"[phase_{phase_letter}] waiting {wait:.1f}s before request {i+1}",
                    flush=True,
                )
                time.sleep(wait)

        last_start_perf = time.perf_counter()
        print(f"[phase_{phase_letter}] request {i+1}/{count} starting", flush=True)
        raw = one_shot_request(api_key=api_key, content=content, max_tokens=1)
        raw[f"phase_{phase_letter}_index"] = i + 1
        raws.append(raw)
        (run_dir / f"phase_{phase_letter}_{i+1:02d}.json").write_text(
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
            f"[phase_{phase_letter}] request {i+1} status={sm['http_status']} "
            f"pt={sm['prompt_tokens']} latency_ms={sm['latency_ms']} "
            f"interval={interval} Nvcf-Reqid={sm['Nvcf-Reqid']}",
            flush=True,
        )

        if raw.get("http_status") == 429:
            print(
                f"[phase_{phase_letter}] FIRST 429 — stop phase immediately (no retry)",
                flush=True,
            )
            break

    elapsed = time.perf_counter() - phase_t0
    statuses = [s["http_status"] for s in summaries]
    n_ok = sum(1 for s in statuses if s == 200)
    n_429 = sum(1 for s in statuses if s == 429)
    ok_tokens = sum(
        int(s["prompt_tokens"])
        for s in summaries
        if s["http_status"] == 200 and isinstance(s.get("prompt_tokens"), int)
    )
    first_fail = next((s for s in summaries if s["http_status"] != 200), None)

    if n_429 == 0 and n_ok == count:
        classification = f"PHASE_{phase_letter.upper()}_{int(spacing_sec)}S_PACING_ALL_SUCCESS"
        result = "PASS"
    elif n_429 > 0:
        classification = f"PHASE_{phase_letter.upper()}_{int(spacing_sec)}S_PACING_STOPPED_ON_429"
        result = "FAIL"
    else:
        classification = f"PHASE_{phase_letter.upper()}_INCONCLUSIVE"
        result = "FAIL"

    return {
        "result": result,
        "classification": classification,
        "spacing_sec": spacing_sec,
        "requested_max": count,
        "completed": len(summaries),
        "successful": n_ok,
        "statuses": statuses,
        "first_failure": first_fail,
        "elapsed_phase_sec": round(elapsed, 2),
        "approx_successful_prompt_tokens": ok_tokens,
        "requests": summaries,
        "raw_results": raws,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prior-run-dir", default=str(DEFAULT_PRIOR))
    args = ap.parse_args()

    api_key = os.environ.get("NIM_API_KEY", "").strip()
    if not api_key:
        print("NIM_API_KEY is not set.", flush=True)
        return 2

    run_dir = Path(args.prior_run_dir)
    prior_path = run_dir / "report.json"
    if not prior_path.exists():
        print(f"Missing prior report: {prior_path}", flush=True)
        return 2
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    phase_a = prior["phases"]["A"]
    content_chars = int(phase_a["content_chars"])
    content = build_synthetic_content(content_chars)
    print(f"[setup] content_chars={len(content)} (same payload family as A/B/C)", flush=True)

    large_request_budget = 21
    used = 0

    # ── Pre-test gate ─────────────────────────────────────────────────────
    print("[pretest] one ~170k request", flush=True)
    pretest = one_shot_request(api_key=api_key, content=content, max_tokens=1)
    used += 1
    (run_dir / "phase_de_pretest.json").write_text(json.dumps(pretest, indent=2), encoding="utf-8")
    pretest_sm = summarize(0, pretest, None)
    print(
        f"[pretest] status={pretest_sm['http_status']} pt={pretest_sm['prompt_tokens']} "
        f"latency_ms={pretest_sm['latency_ms']} Nvcf-Reqid={pretest_sm['Nvcf-Reqid']}",
        flush=True,
    )

    if pretest.get("http_status") == 429:
        report = {
            "verdict": "PACING_DIAGNOSTIC_CURRENTLY_THROTTLED",
            "A_pretest": pretest_sm,
            "B_phase_d": "NOT RUN",
            "C_phase_e": "NOT RUN",
            "large_requests_used": used,
            "generated_utc": utc_now(),
        }
        out = run_dir / "phase_de_report.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("PACING_DIAGNOSTIC_CURRENTLY_THROTTLED", flush=True)
        print(f"Wrote {out}", flush=True)
        return 3

    if pretest.get("http_status") != 200:
        print(f"PRETEST_FAILED status={pretest.get('http_status')}", flush=True)
        return 4

    # Ensure start-to-start from pretest to D1 respects 15s (conservative)
    time.sleep(15.0)

    # ── Phase D — 15s × ≤10 ───────────────────────────────────────────────
    remaining = large_request_budget - used
    d_count = min(10, remaining)
    phase_d = paced_phase(
        api_key=api_key,
        content=content,
        count=d_count,
        spacing_sec=15.0,
        run_dir=run_dir,
        phase_letter="d",
    )
    used += phase_d["completed"]
    (run_dir / "phase_d.json").write_text(
        json.dumps({k: v for k, v in phase_d.items() if k != "raw_results"}, indent=2),
        encoding="utf-8",
    )
    print(phase_d["classification"], flush=True)

    phase_e: Any
    if phase_d["result"] != "PASS" or phase_d["successful"] != 10:
        phase_e = {
            "result": "NOT RUN",
            "reason": (
                "Phase D did not complete 10/10 successfully. "
                "Per protocol, do not test 20s after a failed 15s phase in the same execution."
            ),
        }
        print("[phase_e] NOT RUN — Phase D incomplete/failed", flush=True)
    else:
        # ≥5 minutes after final Phase-D request
        last_d_end = _parse_utc(phase_d["requests"][-1]["timestamp_utc_end"])
        now = datetime.now(timezone.utc)
        gap = (now - last_d_end).total_seconds()
        wait = max(0.0, 300.0 - gap)
        print(f"[cooldown] after Phase D: wait {wait:.1f}s (need ≥300s)", flush=True)
        if wait > 0:
            time.sleep(wait)

        remaining = large_request_budget - used
        e_count = min(10, remaining)
        if e_count <= 0:
            phase_e = {
                "result": "NOT RUN",
                "reason": "large-request budget exhausted",
            }
        else:
            phase_e = paced_phase(
                api_key=api_key,
                content=content,
                count=e_count,
                spacing_sec=20.0,
                run_dir=run_dir,
                phase_letter="e",
            )
            used += phase_e["completed"]
            (run_dir / "phase_e.json").write_text(
                json.dumps(
                    {k: v for k, v in phase_e.items() if k != "raw_results"}, indent=2
                ),
                encoding="utf-8",
            )
            print(phase_e["classification"], flush=True)

    # Header observations across pretest + D (+ E if run)
    hdr_inputs: list[dict[str, Any]] = [pretest]
    if isinstance(phase_d.get("raw_results"), list):
        hdr_inputs.extend(phase_d["raw_results"])
    if isinstance(phase_e, dict) and isinstance(phase_e.get("raw_results"), list):
        hdr_inputs.extend(phase_e["raw_results"])
    d_headers = header_obs(hdr_inputs)

    # Shortest observed-safe interval from this + prior diagnostics
    prior_safe = [30, 60]  # from A/B/C
    observed_safe: list[int] = list(prior_safe)
    if phase_d.get("result") == "PASS":
        observed_safe.append(15)
    if isinstance(phase_e, dict) and phase_e.get("result") == "PASS":
        observed_safe.append(20)
    shortest = min(observed_safe) if observed_safe else None

    # Recommendation: if 15 failed, don't recommend 15; if 15 passed recommend 15 as shortest observed
    if phase_d.get("result") == "PASS":
        rec_interval = 15
        rec_note = (
            "15s start-to-start completed 10/10 in this limited diagnostic "
            "(observed safe in limited diagnostic — not guaranteed safe)."
        )
    elif isinstance(phase_e, dict) and phase_e.get("result") == "PASS":
        rec_interval = 20
        rec_note = (
            "15s failed; 20s was not run in-session after D failure per protocol. "
            "Prior evidence supports ≥30s; 20s not established in this execution."
        )
        # Actually if D failed E is NOT RUN - so rec stays 30 from prior
        rec_interval = 30
        rec_note = (
            "15s did not fully succeed. Per protocol 20s was not run after D failure. "
            "Shortest interval supported by completed successful diagnostics remains "
            "30s (prior Phase B). Status: observed safe in limited diagnostic — not guaranteed."
        )
    else:
        rec_interval = 30
        rec_note = (
            "15s did not fully succeed; 20s NOT RUN. "
            "Shortest fully successful paced evidence remains 30s from prior Phase B. "
            "Observed safe in limited diagnostic — not guaranteed safe."
        )

    if phase_d.get("result") == "PASS" and isinstance(phase_e, dict) and phase_e.get("result") == "PASS":
        rec_interval = 15
        rec_note = (
            "Both 15s (10/10) and 20s (10/10) succeeded in this diagnostic; "
            "shortest supported by evidence is 15s start-to-start. "
            "Observed safe in limited diagnostic — not guaranteed safe."
        )
    elif phase_d.get("result") == "PASS":
        rec_interval = 15
        rec_note = (
            "15s completed 10/10; 20s "
            + (
                "also completed 10/10"
                if isinstance(phase_e, dict) and phase_e.get("result") == "PASS"
                else str(phase_e.get("result") if isinstance(phase_e, dict) else phase_e)
            )
            + ". Shortest observed-safe interval in evidence is 15s. "
            "Not guaranteed safe."
        )

    report = {
        "diagnostic": "nim_large_context_pacing_phase_d_e",
        "isolation": "outside_experiment0",
        "experiment0_frozen": {
            "run_id": "e0_20261007T132027Z",
            "status": "STOPPED_FOR_REVIEW",
            "completed": "19/60",
            "scientific_analysis": False,
        },
        "generated_utc": utc_now(),
        "large_requests_used": used,
        "large_request_budget_max": 21,
        "A_pretest": {
            "http_status": pretest_sm["http_status"],
            "prompt_tokens": pretest_sm["prompt_tokens"],
            "latency_ms": pretest_sm["latency_ms"],
            "Nvcf-Reqid": pretest_sm["Nvcf-Reqid"],
            "Nvcf-Status": pretest_sm["Nvcf-Status"],
            "finish_reason": pretest_sm["finish_reason"],
        },
        "B_phase_d_15s": {
            k: v for k, v in phase_d.items() if k != "raw_results"
        },
        "C_phase_e_20s": (
            {k: v for k, v in phase_e.items() if k != "raw_results"}
            if isinstance(phase_e, dict)
            else phase_e
        ),
        "D_headers": d_headers,
        "E_comparison": {
            "dense_Exp0_traffic": "repeated mid-episode HTTP 429 on e0_20261007T132027Z",
            "prior_30s": "5/5 success",
            "prior_60s": "5/5 success",
            "current_15s": phase_d.get("classification"),
            "current_20s": (
                phase_e.get("classification")
                if isinstance(phase_e, dict) and "classification" in phase_e
                else phase_e.get("result")
                if isinstance(phase_e, dict)
                else "NOT RUN"
            ),
            "no_specific_unpublished_quota_claimed": True,
        },
        "F_pacing_recommendation": {
            "shortest_interval_supported_by_diagnostic_evidence_sec": rec_interval,
            "status": "observed_safe_in_limited_diagnostic",
            "not_guaranteed_safe": True,
            "notes": rec_note,
            "do_not_apply_to_started_exp0": True,
            "do_not_resume_exp0": True,
        },
    }

    out = run_dir / "phase_de_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = run_dir / "phase_de_report.md"
    md.write_text(_md(report), encoding="utf-8")

    # Update prior report pointer
    prior["phases"]["D"] = {k: v for k, v in phase_d.items() if k != "raw_results"}
    if isinstance(phase_e, dict) and "raw_results" in phase_e:
        prior["phases"]["E"] = {k: v for k, v in phase_e.items() if k != "raw_results"}
    elif isinstance(phase_e, dict):
        prior["phases"]["E"] = phase_e
    prior["phase_de_report"] = "phase_de_report.json"
    prior_path.write_text(json.dumps(prior, indent=2), encoding="utf-8")

    print(f"Wrote {out}", flush=True)
    print(f"Wrote {md}", flush=True)
    return 0


def _md(r: dict[str, Any]) -> str:
    a = r["A_pretest"]
    d = r["B_phase_d_15s"]
    e = r["C_phase_e_20s"]
    h = r["D_headers"]
    cmp_ = r["E_comparison"]
    f = r["F_pacing_recommendation"]
    lines = [
        "# NIM pacing diagnostic — Phases D (15s) & E (20s)",
        "",
        f"Generated: `{r['generated_utc']}`",
        "",
        "Experiment 0 was **not** resumed or modified.",
        "",
        "## A. Pre-test gate",
        "",
        f"- HTTP: `{a['http_status']}`",
        f"- prompt_tokens: `{a['prompt_tokens']}`",
        f"- latency_ms: `{a['latency_ms']}`",
        f"- Nvcf-Reqid: `{a['Nvcf-Reqid']}`",
        "",
        "## B. Phase D — 15-second pacing",
        "",
        f"- Result: **{d.get('result')}** (`{d.get('classification')}`)",
        f"- Successful: `{d.get('successful')}/{d.get('requested_max')}`",
        f"- Elapsed phase sec: `{d.get('elapsed_phase_sec')}`",
        f"- Approx successful prompt tokens: `{d.get('approx_successful_prompt_tokens')}`",
        "",
        "| request | start UTC | start interval | prompt tokens | latency | HTTP | NVCF request ID |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for req in d.get("requests") or []:
        lines.append(
            f"| {req['sequence']} | {req['timestamp_utc_start']} | "
            f"{req['start_to_start_interval_sec']} | {req['prompt_tokens']} | "
            f"{req['latency_ms']} | {req['http_status']} | {req['Nvcf-Reqid']} |"
        )
    if d.get("first_failure"):
        ff = d["first_failure"]
        lines += [
            "",
            f"First failure: seq={ff.get('sequence')} status={ff.get('http_status')} "
            f"at {ff.get('timestamp_utc_start')}",
        ]
    lines += ["", "## C. Phase E — 20-second pacing", ""]
    if e.get("result") == "NOT RUN":
        lines.append(f"**NOT RUN** — {e.get('reason')}")
    else:
        lines += [
            f"- Result: **{e.get('result')}** (`{e.get('classification')}`)",
            f"- Successful: `{e.get('successful')}/{e.get('requested_max')}`",
            f"- Elapsed phase sec: `{e.get('elapsed_phase_sec')}`",
            f"- Approx successful prompt tokens: `{e.get('approx_successful_prompt_tokens')}`",
            "",
            "| request | start UTC | start interval | prompt tokens | latency | HTTP | NVCF request ID |",
            "|---:|---|---:|---:|---:|---:|---|",
        ]
        for req in e.get("requests") or []:
            lines.append(
                f"| {req['sequence']} | {req['timestamp_utc_start']} | "
                f"{req['start_to_start_interval_sec']} | {req['prompt_tokens']} | "
                f"{req['latency_ms']} | {req['http_status']} | {req['Nvcf-Reqid']} |"
            )
    lines += [
        "",
        "## D. Headers",
        "",
        f"- Retry-After: **{h['Retry-After_exposed']}**",
        f"- RPM: **{h['RPM_limit_exposed']}**",
        f"- TPM: **{h['TPM_limit_exposed']}**",
        f"- Remaining quota: **{h['remaining_quota_exposed']}**",
        f"- Reset time: **{h['reset_time_exposed']}**",
        f"- NVCF request ID: **{h['NVCF_request_IDs_exposed']}**",
        "",
        "## E. Comparison",
        "",
        f"- Dense Exp0 traffic → {cmp_['dense_Exp0_traffic']}",
        f"- 30s → {cmp_['prior_30s']}",
        f"- 60s → {cmp_['prior_60s']}",
        f"- 15s → {cmp_['current_15s']}",
        f"- 20s → {cmp_['current_20s']}",
        "",
        "No specific unpublished NVIDIA quota claimed.",
        "",
        "## F. Pacing recommendation",
        "",
        f"- Shortest interval supported by diagnostic evidence: "
        f"**{f['shortest_interval_supported_by_diagnostic_evidence_sec']} s**",
        f"- Status: `{f['status']}` (not guaranteed safe: **{f['not_guaranteed_safe']}**)",
        f"- Notes: {f['notes']}",
        "",
        f"Large requests used: `{r['large_requests_used']}` / `{r['large_request_budget_max']}`",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
