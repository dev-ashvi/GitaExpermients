# Experiment 0 — NVIDIA-First Execution Feasibility Assessment

**Date:** 2026-10-08  
**Mode:** Operational feasibility audit only — **no inference calls, no scientific execution, no `local_hf` activation**  
**Strategy:** NVIDIA-first; OpenRouter/DeepInfra remains unpaid/unimplemented fallback  

---

## Explicit GO/NO-GO verdict

# `NVIDIA_OPERATIONALLY_UNQUALIFIED`

**for clean N=60 scientific collection right now.**

| Decision code | Applies? |
|---|---|
| `NVIDIA_GO_FOR_CLEAN_N60` | **No** — sustained free-NIM capacity for ~3,100 large-context calls is **not** evidenced |
| `NVIDIA_GO_FOR_ENDURANCE_QUALIFICATION` | **Yes (recommended next step)** — single predetermined, non-scientific endurance protocol |
| `NVIDIA_NO_GO_RATE_LIMIT` | **Not yet absolute** — 19/60 completed under dense traffic; free NIM is not proven impossible, but **not proven sustainable** |
| `NVIDIA_OPERATIONALLY_UNQUALIFIED` | **Yes (current status for clean N=60)** |

**Do not promise N=60 completion under an unverified free-tier limit.**

---

## 1. Historical 429 analysis

### 1.1 Aborted scientific run `e0_20261007T132027Z` (ops only)

| Field | Evidence |
|---|---|
| Status | `STOPPED_FOR_REVIEW` → archived `ABORTED_OPERATIONAL_RATE_LIMIT_PRE_ANALYSIS` |
| Completed | **19/60** (indices 0–18) |
| Wall time to 19 complete | **~1.50 h** (13:20:27Z → 14:50:36Z) |
| Mean episode elapsed | **~285 s** |
| First failure | **~1.51 h** from start — episode index **19**, turn **1**, Witness path |
| Subsequent resume failures | Same episode: turns **6–7** Actor path (ops log) |
| Error body (ops) | `Transient NIM HTTP 429: {"status":429,"title":"Too Many Requests"}` |
| Partial quarantines | **3** (fail-and-restart on index 19) |
| Structural calls (completed eps) | **984** Actor+Witness (cost audit) |
| Input tokens (completed) | **~164.2M** recorded |
| Must resume? | **No** — archival exclusion guards remain |

Traffic pattern during success: continuous mid-episode **Actor then Witness** (≈50–54 logical calls/episode), nested retries on failure, **no deliberate inter-call pacing**.

### 1.2 Isolated large-context pacing diagnostics (`diagnostics/runs/nim_rl_20261007T173827Z`)

All probes used ~**170,006** prompt tokens, `max_tokens=1`, **no automatic 429 retries**, stop on first 429.

| Spacing | Result | Successes before stop |
|---|---|---|
| **15 s** | FAIL | **3** → 429 |
| **20 s** | FAIL | **6** → 429 |
| **30 s** (Phase B, n=5) | PASS | **5/5** |
| **30 s** (sustained validation, n=10) | **FAIL** | **8** → 429 |
| **60 s** (Phase C, n=5) | PASS | **5/5** |

429 responses in diagnostics:

- Body: problem+json `Too Many Requests` (42-byte body typical)
- **`Retry-After`: null / not exposed**
- **No RPM/TPM / X-RateLimit-* headers** observed on 200 or 429
- Latency on 429 often **~150–160 ms** (rejected before useful generation)

Final diagnostic note (on-file): *do not infer a specific unpublished TPM quota*; *no further pacing exploration* without a new hypothesis.

### 1.3 What can / cannot be concluded about the limit type

| Candidate constraint | Evidence | Conclusion |
|---|---|---|
| Simple RPM (e.g. “40 RPM”) | Forum/FAQ “up to 40 RPM”; Exp0 mid-episode rate is far below 40 logical calls/min once generation latency (~seconds–tens of s) dominates | **Unlikely sole explanation** for mid-episode 429 after ~1.5 h of success |
| Tokens / rolling window | Dense Exp0 + ~170k diagnostic bursts hit 429 after limited successes; no header math | **Plausible**, **not proven** |
| Concurrent request limit | Diagnostics were serial; Exp0 is serial per process | **Unlikely primary** |
| Dynamic / traffic-dependent throttle | NVIDIA forum statements: free limits depend on model, use-case, **overall traffic**; 429 below advertised RPM reported by others | **Plausible** |
| Daily allocation | 19 episodes (~164M tokens) then hard fail; resumes still 429 same day | **Possible**; **not identifiable** from headers |
| Nested retry amplification | Failures after “Actor/Witness failed after retries” | **Amplifies** load once throttling starts; does not explain initial onset alone |

**Authoritative exact quota for `nvidia/nemotron-3-super-120b-a12b` on integrate.api was not established from official machine-readable docs in this audit.**

---

## 2. Official quota evidence

| Source class | Finding |
|---|---|
| NVIDIA integrate API reference pages | Document chat completions; **do not publish model-specific free RPM/TPM tables** usable as Exp0 engineering truth |
| NVIDIA Developer Forums (NIM / Access) | Free tier often described as **“up to 40 RPM”**, **model- and traffic-dependent**, **not manually increasable** on free keys; deploy/pay for higher capacity |
| This project’s headers | **No Retry-After; no RPM/TPM remaining/reset headers** on observed 200/429 |
| Account dashboard secrets | **Not inspected** (and must not be logged) |

**Statement required by this audit:**  
**Authoritative, model-exact free-tier limits for Nemotron-3-Super-120B on the hosted endpoint used by Exp0 cannot be established from available official documentation and local evidence alone.**

---

## 3. Retry-amplification analysis

Frozen (unchanged):

- Actor `_call_api`: **3** outer attempts  
- Witness `evaluate`: **3** outer attempts on errors/parse  
- `NimChatProvider.complete`: **3** inner attempts  
- Max underlying HTTP posts per logical Actor generation under persistent 429: **3 × 3 = 9** (measured in P0 fault tests)

| Effect | Assessment |
|---|---|
| Quota consumption | Each 429 attempt still counts as a request against opaque free-tier policy |
| Recovery | Nested backoff **extends** pressure after throttle onset; Exp0 stop-for-review is correct but only after amplification |
| Scientific validity | Retries do not change sampling params; they **do** change wall-clock and failure clustering |
| Proposed amendment (not applied) | **Single retry owner** (provider **or** Actor/Witness), preserve scientific thresholds; qualify separately before clean N=60 |

**Do not change frozen retry counts in this phase.**

---

## 4. Execution-strategy comparison

Assumptions for wall-clock: ~3,107 logical calls / N=60; ~285 s/episode observed under continuous mode; pacing diagnostics used **count-only** large prompts (not full Actor+Witness generation).

| Strategy | Scientific validity | Wall-clock (order) | 429 likelihood | Protocol risk | Engineering need | Schedule / resume |
|---|---|---|---|---|---|---|
| **A. Continuous + “conservative” pacing** | High if schedule frozen & blind | If forced ~30–60 s between **every** logical call: **tens of hours** (cost audit: 30 s spacing alone ≥~26 h lower bound) | **High** — 30 s failed sustained validation after 8 large calls | Low if pacing is condition-blind | Inter-call sleep + ops telemetry | New schedule; resumable pauses OK if immutable slots |
| **B. One episode + cooldown** | High if cooldown **not** condition-dependent | 60 × (episode + cooldown); e.g. +10–30 min cool → **many hours–days** | Medium–high; unknown recovery half-life | Medium if cooldowns adapt to failures in a biased way | Episode barrier + fixed cooldown | Same |
| **C. Scheduled batches + long breaks** | High if batch boundaries ignore outcomes/conditions | Multi-day | Unknown; may help daily quotas **if they exist** | Medium (time drift) | Batch launcher; ops journal | Same |
| **D. Daily fixed episode budget** | High if budget set a priori | Days to weeks | May match opaque daily caps | Low if fixed & blind | Daily stop switch | Same |
| **E. One clean run + resumable operational pauses** | **Preferred validity pattern** if pauses are outcome-blind | Depends on throttle | Requires proven endurance | Low | Already largely present (`STOPPED_FOR_REVIEW` / resume skip completes) | **New** schedule only; never resume archived 19 |
| **F. Stop using NVIDIA free for N=60** | N/A (move to paid later) | N/A | Removes free-tier 429 risk | None if paid path re-qualified | Paid adapter (out of scope now) | — |

**Caching / time-dependent serving:** NIM responses showed large `cached_tokens` on some qualification probes; capacity uses full `prompt_tokens`. Multi-day runs may see cache/warmth differences — record provider_meta; do **not** pace by condition.

---

## 5. Time and condition-confounding assessment

| Risk | Mitigation |
|---|---|
| C1 vs C2 collected on different calendar days with provider drift | Keep **immutable randomized schedule**; process in schedule order; never reorder by condition |
| Stopping when “hard” conditions appear | Forbid outcome- or condition-based early stop; only operational stop |
| Overnight gaps | Allowed if logged as ops events; analysis remains post-freeze on full 60 |
| Retry storms lengthening some episodes | Ops-only; do not drop episodes from primary set except quarantine rules already frozen |
| Using archived 19 episodes | **Forbidden** |

Multi-day execution **can** remain scientifically comparable **if** the above hold and all 60 complete under the same frozen protocol before analysis.

---

## 6. Recommended pacing strategy (if anything)

**No scientifically authorized pacing policy for clean N=60 yet.**

Diagnostics show:

- 15/20 s: fail quickly  
- 30 s: short bursts pass; **sustained fails**  
- 60 s: only **5** successes demonstrated  

Therefore **do not** recommend “run N=60 at 30 s” or “at 60 s” as sufficient.

**Only justified recommendation:** run a **new bounded endurance qualification** (Section 7) with a **pre-registered** spacing hypothesis (suggest **60 s start-to-start** between large engineering calls, or episode-barrier + fixed cooldown — pick one beforehand), stop on first 429, no nested retries, no adaptive stretching.

---

## 7. Proposed bounded endurance qualification (design only — **do not execute now**)

### Purpose

Test whether free NIM can sustain a **predetermined** volume of **representative large-context** calls without 429 — **not** whether a few calls succeed.

### Protocol sketch

| Element | Specification |
|---|---|
| Model | `nvidia/nemotron-3-super-120b-a12b` |
| Payload | Engineering fixture ≈ worst-case / ~170k–208k prompt (existing qualification bodies); `max_tokens=1` or tiny non-scientific completion |
| Client | Single-shot (reuse Stage B `post_chat_completions_once`) — **0 nested retries** |
| Pacing | **Fixed** start-to-start interval chosen a priori (candidate: **60 s**) |
| Budget | e.g. **N = 40** successful calls **or** **~8M prompt tokens** — whichever first; **hard stop** |
| Stop | First HTTP **429**, model mismatch, missing usage, or integrity fail |
| Logging | Timestamps, latency, status, headers, `usage`, cached_tokens, req id — **no** scientific episode ledgers |
| Forbidden | Extending N after near-miss; trying 15/20/30 again without new hypothesis; touching archived run |

### What it can establish

- Whether **≥40** serial large calls at 60 s survive without 429 on this account/day  
- Header behavior under sustained load  
- Rough lower bound on free-tier endurance  

### What it cannot establish

- Full N=60 Exp0 (~3.1k **generation** calls with Actor+Witness density)  
- Exact RPM/TPM formula  
- Tomorrow’s traffic-dependent quota  
- Scientific outcome quality  

---

## 8. Tokenizer activation readiness (`local_hf`)

| Check | Status |
|---|---|
| NIM Stage B evidence `PASSED` / `evidence_validated` | **Yes** |
| Artifact + template hashes bound | **Yes** |
| Profile `nvidia-nim` only | **Yes** (not DeepInfra) |
| Context profile 1M verified for NIM | **Yes** in engineering_config |
| Per-request gate + UNVERIFIED fail-closed without evidence | **Yes** |
| With PASSED evidence, counter can return `verified` | **Yes** |
| Default scientific mode | Still **`unavailable`** (correct until pre-launch approval) |
| Extra live count calls if `local_hf` | **No** (local HF path) |
| Activate in this task? | **No** |

**Readiness:** Safe to activate **`local_hf` for `nvidia-nim` only** after explicit pre-launch approval **and** operational endurance posture is accepted — **not** a substitute for rate-limit endurance.

---

## 9. Operational cost and wall-clock implications

| Item | Estimate | Caveat |
|---|---|---|
| Free NIM $ cost | **$0** API fee | Time/ops cost only |
| Continuous 60 eps @ ~285 s | **~4.8 h** compute-ish | **Already failed** denser pattern after 19 |
| +30 s between all logical calls | **≥~26 h** spacing lower bound | Still **not** proven sustainable |
| +60 s between all logical calls | **≥~52 h** | Only 5-call evidence |
| Multi-day / daily budgets | Days–weeks | May be only free-tier path if endurance fails at 60 s |
| Sunk aborted run | ~164M input tokens ops | Excluded from science |

---

## 10. Decision framework (criteria)

### `NVIDIA_GO_FOR_ENDURANCE_QUALIFICATION`

- Engineering harness tests green; tokenizer NIM-qualified; archived run excluded  
- **and** clean N=60 is desired but sustained free-tier capacity is unproven  
→ **Met now.**

### `NVIDIA_GO_FOR_CLEAN_N60`

- Endurance qual **passes** predetermined budget without 429  
- **and** `local_hf` activation approved for `nvidia-nim`  
- **and** new immutable N=60 schedule created (never reuse archived 19)  
- **and** ops plan is outcome-blind with logged pauses  
→ **Not met.**

### `NVIDIA_OPERATIONALLY_UNQUALIFIED`

- Cannot yet claim reliable complete N=60 on free NIM  
→ **Met now (for clean N=60).**

### `NVIDIA_NO_GO_RATE_LIMIT`

- Endurance qual fails at conservative predetermined pacing **or** official policy states free tier unsuitable for this workload after confirmation  
→ **Reserve** until endurance result exists; do not declare absolute NO-GO solely from 15/20/30 s short diagnostics.

---

## 11. Minimal next implementation steps (await approval)

1. **Approve & run** one bounded endurance qualification (Section 7) — no science.  
2. If fail → document `NVIDIA_NO_GO_RATE_LIMIT` (free) and reopen paid DeepInfra path under prior feasibility plan.  
3. If pass → separate approval to: activate `local_hf` for `nvidia-nim`; optionally adopt single-retry-owner amendment; create **new** N=60 schedule; start clean collection with outcome-blind resumable pauses.  
4. Never resume `e0_20261007T132027Z`.

---

## 12. Remaining blockers

1. **Unverified free-tier endurance** for Exp0-scale call volume  
2. **No machine-readable official quota** for this model/account  
3. **Scientific mode still `unavailable`** (intentional until pre-launch approval)  
4. **Nested 9× retry amplification** still live in scientific path  
5. **30 s pacing not sustained**; 60 s under-tested  
6. Paid fallback not implemented (by design this task)

---

## Constraints honored

No scientific execution; no new schedule; no inference; no paid APIs; no OpenRouter adapter; no scientific outcome inspection; no protocol/retry/`local_hf` changes; no archived-run resume; no Git; artifacts preserved.

**STOP.** Await approval — recommended first action is **endurance qualification only**, not clean N=60.
