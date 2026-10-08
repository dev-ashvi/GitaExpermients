# Experiment 0 — NVIDIA Retry-Policy Amendment Proposal (v1)

**Status:** `RETRY_AMENDMENT_V1_CONDITIONALLY_APPROVED` — **validated, not yet activated**  
**Flag:** `experiment0.engineering_config.RETRY_AMENDMENT_V1_ENABLED = False`  
**Validation:** `EXPERIMENT0_RETRY_AMENDMENT_V1_VALIDATION_REPORT.md`  
**Date:** 2026-10-08  

This document does **not** change frozen scientific sampling, prompts, metrics, N, or Witness JSON rules. It defines an **infrastructure** change to how HTTP failures are handled on the NVIDIA path.

---

## 1. Current frozen behavior (unchanged while flag is False)

| Layer | Behavior |
|---|---|
| Actor `_call_api` | Up to `API_MAX_RETRIES` (3) outer attempts |
| Witness `evaluate` | Up to 3 outer attempts on errors/parse (Witness JSON parse policy unchanged) |
| `NimChatProvider.complete` | Up to 3 inner attempts on HTTP 429 / 5xx / transport blips |
| Max HTTP posts per logical Actor generate under persistent 429 | **3 × 3 = 9** |
| Global pacing | Every physical HTTP attempt obeys ≥60 s start-to-start **independently** of this amendment |

Under free-tier throttling, nested 429 retries **amplify** load and can exhaust episode attempts without improving scientific validity.

---

## 2. Approved amendment v1 (activate only at final launch auth)

| Condition | Action when `RETRY_AMENDMENT_V1_ENABLED=True` |
|---|---|
| **HTTP 429** | **Exactly 1** physical HTTP attempt for the logical call, then `TerminalOperationalError` → run `STOPPED_FOR_REVIEW`. No Actor/Witness re-issue. |
| **Transient HTTP 5xx** | **At most 2** physical HTTP attempts **total** for the logical call (all layers), then terminal stop. |
| **Ambiguous transport timeout** | **1** physical attempt → terminal stop; **no** blind re-issuance. |
| **Malformed Witness JSON** | **Frozen scientific treatment unchanged** (`WitnessParseError` / ValueError path; up to 3 Witness evaluate retries). Never classified as HTTP 429. |
| **Every attempt** | Through `GlobalHttpPacer` (≥60 s start-to-start; no overlap). |

### Terminal exception design

`TerminalOperationalError` subclasses **`BaseException`**, not `Exception`, so Experiment 1 Actor/Witness `except Exception` retry loops **cannot** catch and re-issue NVIDIA calls after 429/timeout. Episode runner and `run_one_episode` catch it explicitly and map to operational stop metadata.

---

## 3. Scientific implications

| Question | Assessment |
|---|---|
| Sampling / prompts / sources / metrics / N / C1–C2 / 25-turn script? | **Unchanged** |
| Witness JSON retry policy? | **Unchanged** |
| Episode failure timing under 429? | **Earlier** — stop after 1 physical attempt vs up to 9 |
| Inclusion of completed episodes? | **Unchanged** |
| N=60 completion probability? | **Mixed** — less quota burn under throttle; more frequent ops pauses; long-run completion may improve if resumes stay outcome-blind |
| Condition/time confounding from pauses? | Mitigated if pauses are ops-only and schedule order immutable |

Analysis footnotes for an amended clean N=60 must record amendment id/version and that failure timing differs from frozen nested-retry collection.

---

## 4. Activation checklist (final launch authorization only)

1. Explicit launch approval including amendment activation  
2. Set `RETRY_AMENDMENT_V1_ENABLED = True`  
3. Activate `local_hf` under separate approval if required  
4. Create **new** immutable N=60 schedule  
5. Manifest must record `ops.retry_amendment_v1` via `amendment_provenance()`  
6. Do **not** mix amended and non-amended episodes in one primary dataset  
7. Re-run full test suites after flipping the flag  

---

## 5. Test evidence (summary)

See `EXPERIMENT0_RETRY_AMENDMENT_V1_VALIDATION_REPORT.md`.

- Persistent 429 → 1 physical attempt  
- Persistent 500 → 2 physical attempts  
- Timeout → 1 attempt, no re-issue  
- 5xx then success → continues  
- Witness malformed JSON → frozen 3 retries  
- Actor outer loop cannot retry terminal 429  
- Phase stops: Actor RAW / Witness RAW / revision / FINAL  
- Quarantine / resume / archival / frozen hashes  
- Full suites: **233 passed** (baseline was 212)  

---

## 6. Non-goals

- No OpenRouter / DeepInfra  
- No change to Witness JSON schema or scientific parse thresholds  
- No automatic activation of this flag before final N=60 authorization  
- No silent reduction of frozen retry counts while the flag remains False  
