# NIM pacing diagnostic — Phases D (15s) & E (20s)

Generated: `2026-10-07T18:35:40.032231Z`

Experiment 0 was **not** resumed or modified.

## A. Pre-test gate

- HTTP: `200`
- prompt_tokens: `170006`
- latency_ms: `974`
- Nvcf-Reqid: `984a0f1b-9a16-43ca-adb5-23b107defd41`

## B. Phase D — 15-second pacing

- Result: **FAIL** (`PHASE_D_15S_PACING_STOPPED_ON_429`)
- Successful: `3/10`
- Elapsed phase sec: `45.16`
- Approx successful prompt tokens: `510018`

| request | start UTC | start interval | prompt tokens | latency | HTTP | NVCF request ID |
|---:|---|---:|---:|---:|---:|---|
| 1 | 2026-10-07T18:34:54.871056Z | None | 170006 | 1230 | 200 | 50bc685f-f0f4-4305-83df-1f1c0f138b54 |
| 2 | 2026-10-07T18:35:09.871305Z | 15.000249 | 170006 | 980 | 200 | 0ed0d781-e945-45f3-b55b-3637feee42f7 |
| 3 | 2026-10-07T18:35:24.871448Z | 15.000143 | 170006 | 1361 | 200 | c54366eb-cba2-4889-a9c7-1649897b73bc |
| 4 | 2026-10-07T18:35:39.871302Z | 14.999854 | None | 159 | 429 | None |

First failure: seq=4 status=429 at 2026-10-07T18:35:39.871302Z

## C. Phase E — 20-second pacing

**NOT RUN** — Phase D did not complete 10/10 successfully. Per protocol, do not test 20s after a failed 15s phase in the same execution.

## D. Headers

- Retry-After: **False**
- RPM: **False**
- TPM: **False**
- Remaining quota: **False**
- Reset time: **False**
- NVCF request ID: **True**

## E. Comparison

- Dense Exp0 traffic → repeated mid-episode HTTP 429 on e0_20261007T132027Z
- 30s → 5/5 success
- 60s → 5/5 success
- 15s → PHASE_D_15S_PACING_STOPPED_ON_429
- 20s → NOT RUN

No specific unpublished NVIDIA quota claimed.

## F. Pacing recommendation

- Shortest interval supported by diagnostic evidence: **30 s**
- Status: `observed_safe_in_limited_diagnostic` (not guaranteed safe: **True**)
- Notes: 15s did not fully succeed; 20s NOT RUN. Shortest fully successful paced evidence remains 30s from prior Phase B. Observed safe in limited diagnostic — not guaranteed safe.

Large requests used: `5` / `21`

