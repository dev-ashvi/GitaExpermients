# Experiment 0 — NVIDIA Free NIM Endurance Screening Report

**Date:** 2026-10-08  
**Authorization:** `NVIDIA_GO_FOR_ENDURANCE_QUALIFICATION`  
**Run ID:** `nim_endurance_20261008T055334Z`  
**Artifacts:** `diagnostics/runs/nim_endurance_20261008T055334Z/`  

---

## Classification

# `NVIDIA_LARGE_INPUT_SCREEN_PASSED`

All **40/40** predetermined large-context requests succeeded at **60 s** start-to-start with **zero** HTTP 429s.

**This is not** `NVIDIA_GO_FOR_CLEAN_N60`.

---

## 1. Exact test configuration

| Parameter | Value |
|---|---|
| Model | `nvidia/nemotron-3-super-120b-a12b` |
| Endpoint | `https://integrate.api.nvidia.com/v1/chat/completions` |
| Client | `post_chat_completions_once` (no retries) |
| Max attempts | **40** (including failures) |
| Target pacing | **60.0 s** start-to-start |
| Overlap | Forbidden (next starts only after prior completes + schedule) |
| `max_tokens` | **1** |
| `enable_thinking` | `false` via `chat_template_kwargs` |
| Fixtures (rotation) | `worst_case_actor` → `worst_case_witness` → `short_actor_t1` → `short_witness` → `multi_message_actor` → `revision_shaped_actor` (repeat) |
| Input size | ~168k–208k prompt tokens per call |
| Scientific content | **None** |
| Adaptive pacing | **None** |
| Nested retries | **0** |

**Preflight:** FROZEN_MANIFEST 14/14; NIM tokenizer evidence PASSED; archived run blocked; fixture hashes OK; mode `unavailable`; single-shot client confirmed; key present (not logged).

**Free entitlement:** Same free NIM integrate path as prior Exp0/diagnostics; billing portal not queried. No OpenRouter/paid calls.

---

## 2–4. Attempts, successes, failures

| Metric | Value |
|---|---:|
| Attempts | **40** |
| Successful (HTTP 200) | **40** |
| Failed | **0** |
| First failure | **None** |
| Stop reason | `COMPLETED_40` |
| Model returned | Always `nvidia/nemotron-3-super-120b-a12b` |

---

## 5. Actual pacing statistics

| Metric | Value |
|---|---:|
| Target interval | 60.0 s |
| Intervals recorded | 39 |
| Min / mean / max interval | **60.0 / 60.0 / 60.0** s |
| Wall-clock total | **2341.4 s (~39.0 min)** |
| Request duration min / mean / max | 0.78 / 1.74 / 7.39 s |

No request exceeded 60 s duration; schedule never had to defer beyond the fixed start-to-start wait.

---

## 6. Cumulative tokens

| Metric | Value |
|---|---:|
| Cumulative accepted **input** tokens | **7,024,907** |
| Cumulative **output** tokens | **40** (1 each) |
| Approx mean input / success | ~175,623 |

---

## 7. Cached-token observations

| Metric | Value |
|---|---|
| Cached tokens (min–max observed) | **167,024 – 205,920** |
| Capacity-relevant count | Provider `prompt_tokens` (full sequence); cache does not reduce reported prompt size |

Heavy prompt caching was present throughout; screen still exercised large reported `prompt_tokens`.

---

## 8. HTTP 429 and headers

| Item | Result |
|---|---|
| HTTP 429 count | **0** |
| Non-200 statuses | **0** |
| Retry-After | N/A (no 429) |
| Rate-limit headers | Not required for pass; prior diagnostics showed none on 429 |

---

## 9. Does this support further NVIDIA use?

**Yes, limited support for continued NVIDIA-first engineering**, under constraints:

- Free NIM **can** sustain **40** serial ~170–208k **count-only** calls at **60 s** spacing on this account/session without 429.  
- This **improves** on prior short diagnostics where 15/20 s failed and 30 s failed under sustained validation after 8 large calls.  
- It **does not** prove Exp0-scale scientific collection.

---

## 10. Limits of generalizing to full scientific generation

| Screen condition | Experiment 0 scientific condition |
|---|---|
| `max_tokens=1` | Actor **800**, Witness **1600** |
| ~1 call / 60 s | Dense mid-episode Actor→Witness (often ≪60 s between logical calls) |
| ~40 calls | ~**3,107** projected calls for N=60 |
| ~7.0M input tokens | ~**518M** projected input |
| No nested retries | Up to **9** HTTP attempts per logical call on failure |
| Count-only / length finish | Full generations, longer occupancy, different throttle surface |

**Indispensable additional evidence before clean N=60 (minimum):**

1. **Generation-aware endurance** — same 60 s (or stronger) spacing but with **non-trivial `max_tokens`** (e.g. 800 or dual Actor/Witness-shaped pair) under a **hard predetermined budget**, stop on first 429; **or**  
2. Explicit acceptance that scientific collection will use **forced ≥60 s between every provider call** (including mid-episode), with documented wall-clock (≥~52 h spacing lower bound alone) and still-uncertain sustainability for 3k+ **generation** calls.

Without (1) or a deliberate paced scientific ops plan validated for **generation** load, operational sustainability of free NIM for full Exp0 remains **not established**.

Indefinite further 15/20/30 s count-only pacing exploration is **not** recommended.

---

## 11. Recommendation

| Option | Recommendation |
|---|---|
| Immediate clean N=60 on free NIM (dense Exp0 pattern) | **No** |
| Controlled NVIDIA path after **generation-load** screen or forced 60 s scientific pacing plan | **Conditional** — next decision point |
| Paid OpenRouter→DeepInfra fallback | Remain ready per prior feasibility plan if generation screen fails or forced pacing is unacceptable |
| Label as `NVIDIA_GO_FOR_CLEAN_N60` | **Do not** |

**Suggested next approval (not executed here):** one bounded **generation** endurance screen (fixed N, fixed spacing, `max_tokens` ∈ {800} or Actor+Witness pair, no retries, stop on 429) — then decide controlled NVIDIA execution vs paid fallback.

---

## Integrity

- `local_hf` **not** activated  
- Exp0 **not** launched; no new schedule  
- Archived run **not** resumed  
- No scientific outcomes inspected  
- No protocol / retry / OpenRouter / Git changes  
- No code changes requiring regression re-run (script under `diagnostics/` only)

**STOP.** Await approval before any scientific collection or further screens.
