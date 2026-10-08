# Final 30-second sustained NIM pacing validation

Generated: `2026-10-07T19:15:02.137964Z`

**FINAL_30S_VALIDATION_FAILED_ON_429**

Pre-test: status=200 pt=170006 Nvcf-Reqid=82095e53-23c8-43e0-a9e6-258170bbdd93

| # | start UTC | interval | tokens | latency | HTTP | NVCF ID |
|---:|---|---:|---:|---:|---:|---|
| 1 | 2026-10-07T19:11:01.981235Z | None | 170006 | 630 | 200 | 55574c7a-146a-41f7-a48a-3760218603be |
| 2 | 2026-10-07T19:11:31.981336Z | 30.000101 | 170006 | 2704 | 200 | 4c63b8b9-6f42-467f-9626-708f49b1946b |
| 3 | 2026-10-07T19:12:01.981394Z | 30.000058 | 170006 | 1188 | 200 | 5ccacd2c-a68b-461c-aca6-70e09726aceb |
| 4 | 2026-10-07T19:12:31.981445Z | 30.000051 | 170006 | 1130 | 200 | 0057b26c-94c1-4047-99b4-6120bf5d03df |
| 5 | 2026-10-07T19:13:01.981845Z | 30.0004 | 170006 | 642 | 200 | dcf98eb4-700a-4fda-ac45-34b1d221994f |
| 6 | 2026-10-07T19:13:31.981981Z | 30.000136 | 170006 | 917 | 200 | 0a810842-107d-4b74-b0ea-6128bdaa59c8 |
| 7 | 2026-10-07T19:14:01.982158Z | 30.000177 | 170006 | 1152 | 200 | 026e805d-be4b-4217-a2c5-16854c5139c4 |
| 8 | 2026-10-07T19:14:31.982286Z | 30.000128 | 170006 | 1118 | 200 | 10be7b3c-0091-4150-9880-88c6735394cb |
| 9 | 2026-10-07T19:15:01.982491Z | 30.000205 | None | 154 | 429 | None |

| Spacing | Result |
|---|---|
| Dense Exp0 | repeated 429 |
| 15 s | 3 successes → 429 |
| 20 s | 6 successes → 429 |
| 30 s initial | 5/5 success |
| 30 s sustained | FINAL_30S_VALIDATION_FAILED_ON_429 |
| 60 s | 5/5 success |

Experiment 0 was not resumed or modified. No further pacing intervals tested.
