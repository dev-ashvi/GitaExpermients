# Independent 20-second NIM pacing diagnostic

Generated: `2026-10-07T19:00:29.500670Z`

Classification: **PHASE_E_20S_PACING_FAILED_ON_429**

## Pre-test

- status=200 pt=170006 latency_ms=1331 Nvcf-Reqid=771011d8-97ab-42ba-a7de-47104520e031

## Requests

| # | start UTC | interval | tokens | latency | HTTP | NVCF ID |
|---:|---|---:|---:|---:|---:|---|
| 1 | 2026-10-07T18:58:29.351153Z | None | 170006 | 1223 | 200 | a6e42af9-b212-4857-a6db-b15eaf63025b |
| 2 | 2026-10-07T18:58:49.350658Z | 19.999505 | 170006 | 998 | 200 | 8eb51ff6-856d-446d-8353-47d18544c516 |
| 3 | 2026-10-07T18:59:09.350944Z | 20.000286 | 170006 | 1129 | 200 | 7bb87d94-3610-468d-bce4-59133dd7ed4d |
| 4 | 2026-10-07T18:59:29.351465Z | 20.000521 | 170006 | 989 | 200 | f986181c-34c0-4abf-a2a6-a9c7a36fc7ae |
| 5 | 2026-10-07T18:59:49.351950Z | 20.000485 | 170006 | 741 | 200 | ea7125a3-b6aa-465d-9817-5301e1205f36 |
| 6 | 2026-10-07T19:00:09.353084Z | 20.001134 | 170006 | 3427 | 200 | b885841d-abf2-479d-95c3-ddb154ae7274 |
| 7 | 2026-10-07T19:00:29.352119Z | 19.999035 | None | 144 | 429 | None |

## Comparison

| Spacing | Sustained result |
|---|---|
| Dense Exp0 | repeated 429 |
| 15 s | 3 successes → 429 |
| 20 s | PHASE_E_20S_PACING_FAILED_ON_429 |
| 30 s | 5/5 success |
| 60 s | 5/5 success |

**Shortest tested interval that completed its entire diagnostic sequence:** **30 s**

**Strength of evidence:** Evidence strength differs by design: 20s and 15s used sustained 10-request targets; 30s/60s prior tests used 5-request sequences. A 10/10 success at 20s is stronger for that interval than a 5/5 at 30s for cross-interval comparison of robustness, but does not guarantee production safety. No unpublished NVIDIA TPM quota inferred.

Headers: {'Retry-After_exposed': False, 'RPM_exposed': False, 'TPM_exposed': False, 'remaining_quota_exposed': False, 'reset_time_exposed': False, 'NVCF_request_ID_exposed': True}

Experiment 0 was not resumed or modified.
