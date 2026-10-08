# Combined NIM large-context rate-limit diagnostic (A/B/C)

Generated: `2026-10-07T18:21:43.313553Z`

Experiment 0 was **not** resumed or modified.

## A. Phase A — large-context verification

- Result: **PASS**
- HTTP status: `200`
- prompt_tokens: `170006`
- latency_ms: `2630`
- finish_reason: `length`
- Nvcf-Reqid: `4225990b-98c8-4e54-be51-06d51f14a16a`
- Nvcf-Status: `fulfilled`

## B. Phase B — 30-second pacing

- Result: **PASS** (`PHASE_B_30S_PACING_ALL_SUCCESS`)
- Spacing: `30.0` s
- Statuses: `[200, 200, 200, 200, 200]`

- B1: status=200 pt=170006 latency_ms=1228 Nvcf-Reqid=1013f0e5-4bad-42c1-9b42-f476e98a3736 Retry-After=None
- B2: status=200 pt=170006 latency_ms=1137 Nvcf-Reqid=2fa8345d-9539-4159-9abf-64b8b1a3257f Retry-After=None
- B3: status=200 pt=170006 latency_ms=1146 Nvcf-Reqid=1ec81174-473a-48fe-91da-aa904e18efa7 Retry-After=None
- B4: status=200 pt=170006 latency_ms=2246 Nvcf-Reqid=0b68eda7-0d5c-41ec-b4e0-c315b635d5fe Retry-After=None
- B5: status=200 pt=170006 latency_ms=1150 Nvcf-Reqid=ceb4d369-77da-44bc-a273-112b1bd035db Retry-After=None

## C. Phase C — 60-second pacing

- Result: **PASS** (`PHASE_C_60S_PACING_ALL_SUCCESS`)
- Spacing: `60.0` s
- Statuses: `[200, 200, 200, 200, 200]`

- C1: status=200 pt=170006 latency_ms=7130 start=2026-10-07T18:17:42.614427Z end=2026-10-07T18:17:49.744692Z Nvcf-Reqid=d000bb62-aa29-49a8-97e1-ab84005872e8 Nvcf-Status=fulfilled Retry-After=None rate/quota_headers={}
- C2: status=200 pt=170006 latency_ms=9786 start=2026-10-07T18:18:42.616012Z end=2026-10-07T18:18:52.402533Z Nvcf-Reqid=53132158-41bd-408e-b45d-3ed4d4026dfa Nvcf-Status=fulfilled Retry-After=None rate/quota_headers={}
- C3: status=200 pt=170006 latency_ms=842 start=2026-10-07T18:19:42.617352Z end=2026-10-07T18:19:43.459542Z Nvcf-Reqid=6a3de687-48cc-4aaa-823e-2fbbd322782d Nvcf-Status=fulfilled Retry-After=None rate/quota_headers={}
- C4: status=200 pt=170006 latency_ms=1395 start=2026-10-07T18:20:42.617150Z end=2026-10-07T18:20:44.013353Z Nvcf-Reqid=a18eebac-1cb4-4049-8ae5-4f3f3c98cc1e Nvcf-Status=fulfilled Retry-After=None rate/quota_headers={}
- C5: status=200 pt=170006 latency_ms=694 start=2026-10-07T18:21:42.617436Z end=2026-10-07T18:21:43.311552Z Nvcf-Reqid=3c9f2296-0d90-4af0-a53e-c39e2de76d73 Nvcf-Status=fulfilled Retry-After=None rate/quota_headers={}

## D. Header observations

- Retry-After exposed: **False**
- RPM limit exposed: **False**
- TPM limit exposed: **False**
- Remaining quota exposed: **False**
- Reset time exposed: **False**
- NVCF request IDs exposed: **True**
- Header names seen: `['Access-Control-Expose-Headers', 'Connection', 'Content-Type', 'Date', 'Nvcf-Reqid', 'Nvcf-Status', 'Transfer-Encoding', 'Vary']`

## E. Comparison with Experiment 0 (operational only)

- Diagnostic spacing: `{'phase_b_start_to_start_sec': 30, 'phase_c_start_to_start_sec': 60, 'attempts_per_scheduled_request': 1, 'automatic_429_retries': False}`
- Diagnostic prompt-token sizes: `{'target': '~170006', 'phase_a': 170006, 'phase_b': [170006, 170006, 170006, 170006, 170006], 'phase_c': [170006, 170006, 170006, 170006, 170006], 'in_160k_180k_band': True}`
- Exp0 dense-call behavior: Experiment 0 episode execution issues many large-context NIM calls in rapid succession within a turn and across turns (Actor then Witness, plus nested retries on transient errors under the frozen retry budget). On run e0_20261007T132027Z, HTTP 429s repeatedly appeared mid-episode (e.g. around turns 6–7) after bursts of successful generation calls, while completed episodes remained at 19/60 under STOPPED_FOR_REVIEW.
- Consistent with throughput-sensitive throttling: Yes — operationally consistent. Isolated ~170k requests at 30s and 60s start spacing completed without 429 in this diagnostic, whereas Exp0's denser same-model call pattern encountered 429 after short successful bursts. This does not identify a specific unpublished NVIDIA TPM quota.

## F. Recommendation (FUTURE run only)

- Recommended pacing interval: **30 s** between large-context request starts
- Basis: Phase B (30s start spacing) and Phase C (60s start spacing) both achieved 5/5 HTTP 200 on ~170k-token synthetic requests with no automatic retries. 30s is the shortest spacing tested that fully succeeded; 60s also succeeded but is more conservative.
- Do not apply to started Experiment 0: **True**
- Do not resume Experiment 0 from this diagnostic: **True**

