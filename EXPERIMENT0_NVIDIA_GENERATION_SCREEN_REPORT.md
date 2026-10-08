# Experiment 0 — NVIDIA Free NIM Generation-Load Qualification Report

**Date:** 2026-10-08  
**Authorization:** Final bounded generation-load screen after `NVIDIA_LARGE_INPUT_SCREEN_PASSED`  
**Run ID (qualifying):** `nim_generation_20261008T071640Z`  
**Artifacts:** `diagnostics/runs/nim_generation_20261008T071640Z/`  
**Frozen plan:** `diagnostics/runs/nim_generation_20261008T071640Z/FROZEN_PLAN.json`  

**Superseded partial attempt (not a result):** `nim_generation_20261008T070741Z` — aborted after Witness prompts accidentally replaced the large source packet (~3k input tokens). Corrected construction appends the engineering instruction; that partial run is excluded from qualification.

---

## Classification

# `NVIDIA_GENERATION_SCREEN_PASSED`

All **24/24** predetermined large-context generation requests succeeded at **≥60 s** start-to-start with **zero** HTTP 429s, correct model identity, and **full** output budgets on every call (Actor 800 × 12, Witness 1600 × 12).

**This is not** `NVIDIA_GO_FOR_CLEAN_N60`.  
**This does not** authorize launching Experiment 0 without a separate pre-launch approval.

---

## 1. Exact test configuration

| Parameter | Value |
|---|---|
| Model | `nvidia/nemotron-3-super-120b-a12b` |
| Endpoint | `https://integrate.api.nvidia.com/v1/chat/completions` |
| Client | `post_chat_completions_once` (no retries) |
| Max attempts | **24** (including failures) |
| Target pacing | **60.0 s** start-to-start; never overlap |
| Role shape | Alternating **12 Actor / 12 Witness** |
| Actor `max_tokens` | **800** |
| Witness `max_tokens` | **1600** |
| `enable_thinking` | `false` via `chat_template_kwargs` |
| Temperature | `0.0` |
| Input envelope | ~168k–208k provider `prompt_tokens` |
| Base fixtures (rotated) | Actor: `worst_case_actor`, `short_actor_t1`, `multi_message_actor`, `revision_shaped_actor`; Witness: `worst_case_witness`, `short_witness` |
| Generation prompts | Synthetic engineering telemetry/glossary load only (frozen hashes in plan) |
| Adaptive pacing | **None** |
| Nested retries | **0** |
| Scientific schedule / ledger | **Not used** |

**Construction rule (frozen):** Actor — replace short final user turn. Witness — **append** engineering instruction to the large source-packet user message (preserves ~170k context).

**Frozen representativeness thresholds (pre-declared):**

| Threshold | Required | Observed |
|---|---:|---:|
| Total completion tokens | ≥ 14,400 (½ of 28,800 budget sum) | **28,800** |
| Actor completion total | ≥ 4,800 | **9,600** |
| Witness completion total | ≥ 9,600 | **19,200** |

**Preflight:** FROZEN_MANIFEST **14/14**; NIM tokenizer qualification **PASSED** (`2dc98e2afe…`); template/artifact hashes match evidence; archived `e0_20261007T132027Z` resume **blocked**; fixture INDEX hashes OK; `PER_REQUEST_TOKEN_COUNT_MODE=unavailable`; single-shot client confirmed; no paid provider; key present (not logged).

**Free entitlement:** Same free NIM integrate path as prior Exp0/diagnostics and the passed large-input endurance screen; billing portal not queried.

---

## 2–4. Attempts, successes, first failure

| Metric | Value |
|---|---:|
| Attempts | **24** |
| Successful (HTTP 200) | **24** |
| Failed | **0** |
| First failure | **None** |
| Stop reason | `COMPLETED_24` |
| Model returned | Always `nvidia/nemotron-3-super-120b-a12b` |
| Finish reason | Always `length` (hit output budget every call) |
| HTTP 429 | **0** |

---

## 5. Actual pacing statistics

| Metric | Value |
|---|---:|
| Target interval | 60.0 s |
| Intervals recorded | 23 |
| Min / mean / max interval | **60.0 / 61.10 / 73.80** s |
| Wall-clock total | **1483.2 s (~24.7 min)** |
| Request duration min / mean / max | 6.67 / 32.38 / 77.94 s |

When Witness generation exceeded 60 s (~61–78 s on later Witness calls), the next request started only after completion; intervals were recorded honestly. No catch-up overlap.

---

## 6. Cumulative tokens

| Metric | Value |
|---|---:|
| Cumulative accepted **input** tokens | **4,175,564** |
| Cumulative **output** tokens | **28,800** (100% of sum of budgets) |
| Actor output total | **9,600** (12 × 800) |
| Witness output total | **19,200** (12 × 1600) |
| Input min / mean / max | 168,119 / 173,982 / 207,962 |
| Actor input range | 168,119 – 207,962 |
| Witness input range | 168,970 – 170,562 |

---

## 7. Cached-token observations

| Metric | Value |
|---|---|
| Cached tokens (min–max) | **2,288 – 205,920** |
| Requests with `cached_tokens` field | 24/24 |
| Capacity-relevant count | Full provider `prompt_tokens` (cache does not shrink reported prompt size) |

Heavy prompt caching remained common; Witness call #4 showed a low cache hit (2,288) with large non-cached remainder, confirming the screen was not exclusively serving identical warm prefixes.

---

## 8. HTTP 429 and header evidence

| Item | Result |
|---|---|
| HTTP 429 count | **0** |
| Non-200 statuses | **0** |
| Retry-After | N/A |
| Error bodies | None on qualifying run |

---

## 9. Does this support further NVIDIA use?

**Yes — limited support for a carefully paced NVIDIA-first scientific path**, subject to separate pre-launch approval.

Evidence now includes:

1. Count-only large-input screen: 40/40 @ 60 s (`NVIDIA_LARGE_INPUT_SCREEN_PASSED`)  
2. Generation-load screen: 24/24 @ ≥60 s with full Actor/Witness output budgets (`NVIDIA_GENERATION_SCREEN_PASSED`)

Still **not** a proof of ~3,100-call Exp0 capacity, dense mid-episode spacing, nested retries, or multi-day continuity.

---

## 10. Limits of generalizing to full scientific generation

| Screen condition | Experiment 0 scientific condition |
|---|---|
| 24 calls | ~**3,107** projected logical calls for N=60 |
| Forced ≥60 s between HTTP posts | Dense mid-episode Actor→Witness often ≪60 s unless ops policy forces spacing |
| Synthetic engineering prompts | Scientific Actor/Witness protocols, JSON Witness schema, revision loops |
| Retries = 0 | Frozen nested retries up to **9** HTTP posts per logical generation |
| ~25 min wall-clock | Multi-day if ≥60 s enforced on all calls |
| Single session | Overnight gaps, cache warmth, opaque free-tier drift |

**Indispensable before scientific execution (not optional diagnostics churn):**

1. **Separate pre-launch approval** for a **fresh** N=60 schedule (never resume `e0_20261007T132027Z`).  
2. **Fixed ≥60 s inter-call ops policy** applied to every provider HTTP post (including mid-episode), outcome- and condition-blind.  
3. **Documented projected wall-clock** and stop/resume rules (ops-only).  
4. **Decision on retry amplification** — either accept nested ≤9 under paced gaps, or a **separately approved** single-owner retry amendment (not applied in this task).

Further indefinite diagnostic screens are **not** required to make the next decision.

---

## 11. Recommendation

### **A. Proceed toward a fresh, carefully paced NVIDIA N=60 run**  
*(subject to separate pre-launch approval — not authorized by this report)*

Not B (paid fallback) and not C (insufficient evidence): generation-load at 60 s spacing **did** sustain representative output on this account/session.

**If A is approved later, outline (planning only — no schedule created here):**

| Ops element | Proposed fixed policy |
|---|---|
| Inter-call spacing | **≥60.0 s start-to-start** for every NIM HTTP post; never overlap; if a call lasts >60 s, start next only after completion |
| Projected lower bound | ~3,107 × 60 s ≈ **51.8 h** spacing alone; plus generation latency → likely **~2.5–4+ calendar days** depending on Witness duration and pauses |
| Retries | Keep frozen nested retries **or** seek separate approval to collapse to a single retry owner before launch |
| Pauses | Allowed if **condition-independent** and logged as ops events (`STOPPED_FOR_REVIEW` / resume-skip-completes); never pause based on outcomes or C1/C2 |
| Schedule | **New** immutable randomized N=60 only; archived 19 excluded |
| Analysis | Post-freeze after all 60 complete; no mid-run scientific inspection |
| Stop rules | First unexpected operational failure / integrity breach → stop for review; no adaptive pacing hunt |

**Do not** label this milestone `NVIDIA_GO_FOR_CLEAN_N60` until that pre-launch packet is explicitly approved.

---

## Integrity

- `local_hf` scientific mode **not** activated  
- Experiment 0 **not** launched; no new N=60 schedule  
- Archived run **not** resumed; scientific outcomes **not** inspected  
- No protocol / retry / sampling / OpenRouter / DeepInfra / Git changes  
- Diagnostics script only: `diagnostics/nim_generation_screen_60s.py` (no scientific harness edits; regressions not re-run)

**STOP.** Await separate approval before any scientific collection.
