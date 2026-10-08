# Experiment 0 — OpenRouter / DeepInfra Provider Feasibility (Planning Only)

**Date:** 2026-10-08  
**Mode:** Read-only assessment — **no inference calls, no adapter implementation, no purchases**  
**Context:** NVIDIA NIM local tokenizer **PASSED** (7/7, Δ=0), but scientific gate remains **`unavailable`**; free NIM aborted at 19/60 on sustained 429s  
**Archived run:** `e0_20261007T132027Z` remains excluded  

---

## Executive recommendation

| Decision layer | Recommendation |
|---|---|
| Implement OpenRouter→DeepInfra **engineering adapter** + bounded qualification | **CONDITIONAL GO** |
| Authorize clean scientific **N=60** on that path | **NO-GO until** DeepInfra-specific Δ=0, thinking-off fidelity, pin verification, and capacity profile verification all pass |
| Shrink source packet / prompts / turns to fit context | **NO-GO** (forbidden by this task and protocol preservation) |
| Treat NVIDIA tokenizer PASS as DeepInfra PASS | **NO-GO** |

**Primary blockers before scientific use (not before adapter coding):**

1. **Thinking-off semantics** on OpenRouter/DeepInfra are **not established** for our frozen `chat_template_kwargs.enable_thinking=False` path (risk of silent drop or alternate controls).  
2. **DeepInfra `usage.prompt_tokens` Δ=0** vs pinned HF tokenizer is **unproven**.  
3. Advertised **262,144** context is **not** Exp0-verified; Actor envelope fits **only if** DeepInfra counts ≈ NVIDIA (~207,876+800 under 0.85×262k).

---

## 1. Exact identifiers (from public docs; not live-probed this session)

| Layer | Identifier | Status |
|---|---|---|
| Exp0 frozen scientific model string | `nvidia/nemotron-3-super-120b-a12b` | Confirmed in `config/experiment0_config.py` |
| OpenRouter model slug | `nvidia/nemotron-3-super-120b-a12b` | Advertised on OpenRouter model page |
| OpenRouter providers listed | **DeepInfra**, **DekaLLM** | Advertised; default routing may pick either |
| DeepInfra direct model id | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` | Advertised on DeepInfra API docs |
| OpenRouter provider slug (pin) | `deepinfra` (all DeepInfra endpoints); optional `deepinfra/turbo` | From OpenRouter provider-routing docs |
| Base URL (OpenRouter) | `https://openrouter.ai/api/v1` | Standard OpenAI-compatible |
| Base URL (DeepInfra direct) | `https://api.deepinfra.com/v1/openai` | Alternative path (not required if OR pin works) |

**Planning choice:** Prefer **OpenRouter with hard DeepInfra pin** so billing/ops stay in one place, while still enforcing backend identity. Direct DeepInfra remains a fallback engineering option if OpenRouter strips required parameters.

---

## 2. Provider pinning and fallback disabling

### Confirmed (OpenRouter docs)

Request body may include:

```json
"provider": {
  "order": ["deepinfra"],
  "allow_fallbacks": false,
  "only": ["deepinfra"],
  "require_parameters": true
}
```

- `allow_fallbacks: false` → do not silently use DekaLLM (or others) if DeepInfra fails.  
- `only: ["deepinfra"]` → allow-list.  
- `require_parameters: true` → avoid providers that cannot honor requested parameters (useful if thinking controls differ).  
- Default without this is **load-balanced with fallbacks on** — unacceptable for Exp0 reproducibility.

### Per-response verification (required)

| Signal | How to capture | Fail closed if |
|---|---|---|
| Serving provider | OpenRouter generation metadata `provider_name` via `GET /api/v1/generation?id=…` (and any in-response provider fields if present) | Not DeepInfra |
| Upstream id | `upstream_id` / native completion id | Missing when required for audit |
| Model | Response `model` | ≠ requested slug |
| Fallback chain | `provider_responses` on generation metadata | Any non-DeepInfra attempt when pin forbids fallbacks |

**Uncertainty:** Exact in-band chat-completions field for provider name varies by SDK/version; qualification must confirm the observable field(s) before scientific use. Generation API is documented as authoritative for `provider_name`.

---

## 3. Context window vs 85% capacity policy

### Advertised (unverified for Exp0)

| Source | Advertised context |
|---|---|
| OpenRouter model page | **262,144** |
| DeepInfra model page | **262,144** |
| Model card / NIM | Up to **1M** (not what OR/DeepInfra advertise for hosted serving) |

Engineering profile `deepinfra-262k` already exists with `context_limit_verified=False`.

### Frozen capacity arithmetic (must use **DeepInfra-measured** tokens eventually)

\[
0.85 \times 262\,144 = 222\,822.4
\]

Using **NVIDIA-qualified** local/HF counts (Δ=0 on NIM only):

| Role | Prompt (NVIDIA-matched) | Output budget | LHS | Fits 222,822? |
|---|---:|---:|---:|---|
| Actor worst-case | 207,876 | 800 | **208,676** | Yes (headroom ≈ **14,146**) |
| Witness worst-case | 170,414 | 1,600 | **172,014** | Yes (headroom ≈ **50,808**) |

**Headroom risk:** ~6.4% of the Actor budget. Tokenizer/template/router skew of a few percent can erase Actor headroom. **Do not authorize** 262k profile until DeepInfra Δ=0 on worst-case Actor fixture.

**Forbidden:** Reducing S1–S5, constitution, script, or N to “make it fit.”

---

## 4. `enable_thinking=False` / reasoning-off fidelity

### What Exp0 freezes today (NIM path)

`NimChatProvider` sends:

```json
"chat_template_kwargs": {"enable_thinking": false}
```

NIM Stage B used this and observed `reasoning_tokens=0` on minimal probes — **NIM-only**.

### OpenRouter / DeepInfra risk (high)

| Claim | Confidence |
|---|---|
| OpenRouter OpenAI-compatible API accepts arbitrary vendor extras | **Low** — community/OpenAPI alignment notes state unknown top-level fields (including `chat_template_kwargs`) may be **silently dropped** |
| OpenRouter unified `reasoning.effort` (e.g. `"none"`) maps to Nemotron `enable_thinking=False` | **Plausible** via vLLM/Nemotron parsers, **unverified** on our stack |
| OpenRouter model card text about `detailed thinking on` in system prompt | **Conflicts** with Exp0 isolation (must not inject thinking instructions into scientific Actor system prompt without a protocol amendment) |
| DeepInfra direct may accept `chat_template_kwargs` like vLLM | **Unknown** — must probe |

**Qualification requirement:** Demonstrate thinking-off by **orthogonal evidence**, not token counts alone:

- Empty/absent reasoning content when disabled  
- Comparable completion length vs NIM baseline on fixed Witness JSON tasks (engineering fixtures only)  
- Confirm requested control path actually reaches the backend (`require_parameters` + rejection when unsupported)

If only DekaLLM honors a control that DeepInfra ignores (or vice versa), pin must fail closed.

---

## 5. Tokenizer reuse

| Item | Assessment |
|---|---|
| Pinned HF revision `2dc98e2afe4face0e4ce40972a915c45368bd34a` | Reusable **candidate** |
| NIM Δ=0 | **Not transferable** to DeepInfra |
| Required | Fresh **DeepInfra-specific** Stage B: same fixtures, Δ=`local − usage.prompt_tokens` == 0 |
| Evidence binding | New `provider_profile` (e.g. `openrouter-deepinfra-262k`); must **not** reuse `nvidia-nim` PASSED record |

OpenRouter docs state completion `usage` uses the **model’s native tokenizer** — good if true for DeepInfra; still must prove equality empirically.

---

## 6. Adapter integration (preserve Actor/Witness isolation)

### Minimal architecture (plan only)

```
Experiment0EpisodeRunner
  → Actor / Witness (unchanged Exp1 classes)
      → CapacityGatingAnthropicClient
          → NimAnthropicCompatClient-shaped wrapper  OR  shared AnthropicCompatClient
              → OpenRouterChatProvider (new) implementing same ProviderRequest/complete surface
```

### Requirements

| Concern | Plan |
|---|---|
| Message assembly | Reuse `assemble_openai_chat_messages` (already shared with NIM) |
| Isolation | Separate Actor/Witness client instances; no shared conversation state; capacity meta must not log Witness content into Actor-visible artifacts |
| Scientific prompts | No mutation; no injection of “detailed thinking …” into Actor constitution |
| Config isolation | New engineering profile + `OPENROUTER_API_KEY` env; do not alter frozen scientific sampling except documented mapping of thinking-off control **if** qualification proves an equivalent non-prompt mechanism |
| Compat client | Duck-type `messages.create` as today so Actor/Witness sources stay untouched |

Direct DeepInfra OpenAI endpoint can share the same provider class with different `base_url` / model id if OpenRouter cannot forward thinking kwargs.

---

## 7. Telemetry to capture (clean-run readiness)

Per request (ops ledger / provider_meta):

| Field | Purpose |
|---|---|
| Requested model slug | Identity |
| Returned `model` | Drift detection |
| OpenRouter generation `id` | Audit key |
| `provider_name` / pin verification | Backend switch detection |
| `usage.prompt_tokens` / `completion_tokens` | Capacity + cost |
| `prompt_tokens_details.cached_tokens` | Cache vs sequence length (capacity uses full prompt_tokens) |
| `finish_reason` / native finish | Truncation (`length`) vs stop |
| HTTP status / error body (redacted) | 429 / 5xx / param rejection |
| `retries` (should stay auditable) | Amplification monitoring |
| Thinking-control echo / reasoning token counts | Thinking-off check |
| Local capacity check meta (hashes, trust, profile) | Gate audit |

Fail closed on: wrong provider, missing usage, finish_reason=length on Witness JSON, context overflow errors, or unexplained truncation.

---

## 8. Pricing (advertised vs confirmed)

**No live price API call was made in this planning task.** Treat figures as **advertised documentation snapshots** unless re-verified at implementation time.

| Source | Input $/M | Output $/M | Cache | Notes |
|---|---:|---:|---|---|
| OpenRouter model page (aggregate) | **0.08** | **0.45** | Unclear on page | Matches prior ops audit `VERIFIED_FROM_OPENROUTER_MODELS_API` (historical) |
| OpenRouter provider table — DeepInfra | **0.085** | **0.40** | Not fully specified on OR page | Relevant if pinned to DeepInfra |
| OpenRouter provider table — DekaLLM | **0.08** | **0.45** | — | Must **not** be used if DeepInfra-pinned |
| DeepInfra direct docs | **0.085** | **0.40** | Priority/Flex multipliers | Flex 0.8× / Priority 1.5× tiers advertised |
| Third-party aggregators | 0.10 / 0.50; cache read ~0.04 | — | **Unverified** here | Do not budget on these alone |

**Prompt caching:** DeepInfra/aggregators advertise cache reads; OpenRouter usage may expose `cached_tokens` / `cache_discount` on generation metadata. Caching can **lower bill** but must **not** reduce capacity `prompt_tokens` used for the 85% gate (use full prompt token count, as with NIM).

---

## 9. Projected N=60 financial exposure

### Token base (operational prior; not DeepInfra-measured)

From `diagnostics/experiment0_operational_cost_audit.md` (aborted-run extrapolation):

| Quantity | Value | Confidence |
|---|---:|---|
| Projected calls | ~3,107 | Operational estimate |
| Projected input tokens | **518,394,420** | Operational estimate from NIM run |
| Projected output tokens | **1,097,580** | Operational estimate |
| +20% allowance in/out | 622.07M / 1.32M | Sensitivity |

### Cost formula

`cost ≈ (input_M × $/M_in) + (output_M × $/M_out)`

| Price scenario | Mean N=60 | +20% tokens | Notes |
|---|---:|---:|---|
| OR aggregate **0.08 / 0.45** | **~$41.97** | **~$50.36** | Matches prior audit arithmetic |
| DeepInfra-via-OR **0.085 / 0.40** | **~$44.50** | **~$53.40** | Prefer for DeepInfra pin budgeting |
| Aggregator **0.10 / 0.50** | **~$52.39** | **~$62.87** | Conservative unverified |
| Cache-heavy discount | Lower | Lower | **Unverified**; do not plan science on cache savings |

**Retry amplification overlay (not included above):** frozen nested retries can use up to **9 HTTP attempts** per logical Actor call on persistent failure. Paid 429/5xx storms can multiply spend and load. Treat as operational risk → propose infrastructure amendment (single retry owner) **before** long paid runs; **do not change frozen counts in this planning task**.

**Separate:** Qualification probes (~7–12 count-only calls) are **≪ $1** even at worst-case Actor size if limited correctly — still require an explicit Stage B budget.

---

## 10. Bounded engineering qualification plan (no science)

Mirror NIM Stage B discipline; **new evidence profile**.

### Hard rules

- No scientific episodes / schedules / analysis  
- No nested 3×3 retries on qualification client  
- Stop on first 429 without wait-retry loops  
- Do not inspect archived-run scientific text  
- Do not change frozen protocol parameters  

### Minimum probe set (proposed)

| # | Probe | Purpose |
|---|---|---|
| 1 | `minimal_synthetic` | Smoke + thinking-off signals |
| 2 | `short_actor_t1` (~168k) | Large system+sources |
| 3 | `short_witness` | Witness shape |
| 4 | `multi_message_actor` | Multi-turn template |
| 5 | `revision_shaped_actor` | Revision path |
| 6 | `worst_case_actor` (207,876) | **Capacity-critical** |
| 7 | `worst_case_witness` | Capacity-critical |
| 8 | Pin-negative control (optional) | Confirm `allow_fallbacks:false` errors instead of switching to DekaLLM when DeepInfra forced down / ignored — **only if safe/ethical** |

Reuse existing fixture bodies; recompute local counts; require **Δ=0** on DeepInfra/`usage.prompt_tokens` (or documented native count if proven identical).

### Thinking-off probes (engineering fixtures only)

- Fixed short completion with thinking **requested off** vs on (non-scientific prompts)  
- Assert reasoning token / content differences  
- Confirm which request field actually works (`chat_template_kwargs` vs `reasoning.effort`) **without** editing Actor constitution

### Capacity profile gate

Only if Actor worst-case DeepInfra count + 800 ≤ `int(0.85 × verified_limit)` and limit verified from provider evidence → set `context_limit_verified=True` for that profile.

---

## 11. Detection matrix (pre-authorization)

| Failure mode | Detection | Response |
|---|---|---|
| Backend switch (DekaLLM etc.) | `provider_name` ≠ DeepInfra; `provider_responses` shows alternates | Fail closed; no science |
| Unsupported parameters | HTTP 4xx; ignored thinking (reasoning tokens still high); `require_parameters` routing miss | Stop; try DeepInfra-direct only after approval |
| Context truncation | `finish_reason=length` on non-count calls; incomplete Witness JSON; provider context errors | Fail episode / stop run |
| HTTP 429 | Status 429 on single-shot client | Stop qualification / STOPPED_FOR_REVIEW on science; no auto pacing hunt |
| Token mismatch | Δ≠0 vs local HF | Do not mark VERIFIED; keep fail-closed |
| Silent prompt mutation | Request body hash ≠ fixture hash | Integrity fail |
| Nested retry storm | `retries` / HTTP attempt counters | Ops alert; prefer amendment before N=60 |

---

## 12. Provider compatibility matrix

| Requirement | NVIDIA NIM | OpenRouter (unpinned) | OpenRouter→DeepInfra pin | DeepInfra direct |
|---|---|---|---|---|
| Same scientific model family | Yes | Advertised | Advertised | Advertised |
| Sustained N=60 rate limits | **Failed** (429 abort) | Unknown | Unknown (likely better than free NIM) | Unknown |
| Context ≥ Actor 208k @ 85% | 1M verified profile | 262k advertised | 262k advertised | 262k advertised |
| Tokenizer Δ=0 vs pinned HF | **PASS** | Untested | **Required** | **Required** |
| `enable_thinking=False` via `chat_template_kwargs` | Works | **Doubtful / may drop** | Must prove | Must prove |
| Alternate thinking-off API | N/A | `reasoning.effort` candidate | Must prove | Unknown |
| Pin + no fallback | N/A | Defaults bad | **Supported in docs** | N/A (single backend) |
| Per-response backend identity | Model id | Generation `provider_name` | Required | Always DeepInfra |
| Usage.prompt_tokens native | Yes | Docs claim native | Must verify | Yes (typical) |
| Prompt caching | Observed on NIM | Possible | Possible | Advertised |
| Actor/Witness isolation compatible | Yes | Yes if adapter careful | Yes | Yes |
| Est. N=60 $ (ops tokens) | Free tier / 429 | ~$42 @ 0.08/0.45 | ~$44.5 @ 0.085/0.40 | Similar |
| Ready for science now | No (gate closed; 429) | **No** | **No** | **No** |

---

## 13. Retry amplification (risk; no change now)

Frozen behavior:

- Actor outer `API_MAX_RETRIES=3` × provider inner `max_retries=3` → **≤9** HTTP attempts per logical Actor generation on persistent errors  
- Witness evaluate outer × provider → similar for HTTP failures  

**Paid-path risk:** cost and rate-limit amplification.  

**Proposed future infrastructure amendment (not applied here):** single retry ownership (provider **or** Actor/Witness), keep scientific thresholds unchanged, document as engineering change with approval before clean N=60.

Qualification must continue to use **zero nested retries**.

---

## 14. Remaining uncertainties

1. Exact DeepInfra prompt token equality with HF template under OpenRouter serialization.  
2. Whether `chat_template_kwargs` survives OpenRouter.  
3. Whether `reasoning.effort=none` is scientifically equivalent to NIM `enable_thinking=False` without system-prompt edits.  
4. Quantization / serving differences (bf16 vs others) affecting outputs (science) vs tokens (capacity).  
5. Real sustained throughput and 429 behavior under ~3k calls.  
6. Live price confirmation and cache billing.  
7. Whether DekaLLM offers longer context (irrelevant if we forbid fallback).  
8. OpenRouter `models` fallback array accidentally changing model — must disable.

---

## 15. Stop conditions (any → halt qualification / block science)

- HTTP 429 on qualification  
- Δ ≠ 0 on any capacity-critical fixture  
- Provider ≠ DeepInfra under pin  
- Thinking-off control unsupported or ineffective  
- Missing `usage.prompt_tokens`  
- Evidence of truncation on worst-case envelope  
- Any temptation to shrink frozen scientific inputs  
- Attempt to reuse NVIDIA evidence for DeepInfra  

---

## 16. Clear GO / NO-GO

### GO (conditional) — next engineering task after approval

1. Implement `OpenRouterChatProvider` (or generic OpenAI-compatible provider) with **mandatory** DeepInfra pin (`order` + `only` + `allow_fallbacks:false`).  
2. Wire Anthropic-compat + capacity gating; keep scientific mode **`unavailable`**.  
3. Run **DeepInfra Stage B** token + thinking-off qualification (bounded, no nested retries).  
4. Only then propose activating `local_hf` (or provider-bound verified counter) under a **new** evidence profile and a **verified** 262k capacity limit.

### NO-GO now

- Launching Experiment 0 / new N=60 schedule  
- Spending beyond tiny qualification without approval  
- Declaring DeepInfra capacity-safe from NVIDIA numbers alone  
- Changing Experiment 1 or frozen scientific artifacts  
- Enabling OpenRouter without pin / with fallbacks  
- Changing frozen retry counts in this phase  

---

## 17. Suggested next Cursor task (await approval)

**Title:** Implement OpenRouter→DeepInfra pinned provider adapter + Stage B DeepInfra tokenizer/thinking qualification (engineering only)

**Out of scope until further approval:** scientific activation, schedule creation, resume of archived run, retry-policy change, Git commits.

---

## Constraints honored

No external inference; no purchases; no scientific episodes/schedules/analysis; no protocol/Exp1/retry changes; no Git; archived run and exclusion guards preserved.

**STOP.** Await approval before implementing the paid provider adapter or calling OpenRouter/DeepInfra.
