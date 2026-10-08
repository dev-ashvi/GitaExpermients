# Experiment 0 — NVIDIA Final Launch Gate

**Date:** 2026-10-08  
**Authorization:** Activate ops config + dry-run readiness (not scientific launch)  
**Not authorized:** `NVIDIA_GO_FOR_CLEAN_N60` / live N=60 schedule / live inference  

---

## Verdict

# `NVIDIA_FINAL_GATE_PENDING_OPERATOR_CHECK`

Engineering activation, terminal-exception safety, lifecycle dry-runs, and **249** automated tests are green. Two operator confirmations remain before requesting `NVIDIA_GO_FOR_CLEAN_N60`:

1. Host will stay awake for multi-day collection (sleep/hibernate policy — not changed by this task).  
2. Free-tier entitlement / no-surprise-billing understanding (billing portal not queried).

API key presence and disk space are confirmed.

---

## 1. Exact configuration activated

| Setting | Value |
|---|---|
| `RETRY_AMENDMENT_V1_ENABLED` | **`True`** |
| `PER_REQUEST_TOKEN_COUNT_MODE` | **`local_hf`** |
| `PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED` | **`True`** |
| `NIM_HTTP_PACING_ENABLED` | `True` |
| `NIM_HTTP_MIN_START_TO_START_SEC` | `60.0` |
| `ACTIVE_PROVIDER_PROFILE` | `nvidia-nim` |
| Model | `nvidia/nemotron-3-super-120b-a12b` |
| Endpoint | `https://integrate.api.nvidia.com/v1` |
| Context gate | 1,000,000 × **0.85** |
| Amendment budgets | 429→1; 5xx→≤2; timeout→1 |
| Provider fallback | **None** |

Applies only via Experiment 0 engineering modules (`engineering_config` + NIM provider path). Scientific protocol files / sampling unchanged.

**Provenance for future manifests:** `amendment_provenance()` → `manifest["ops"]["retry_amendment_v1"]` with id/version/enabled/budgets/pacing.

---

## 2. Files changed

| File | Change |
|---|---|
| `experiment0/engineering_config.py` | Activate amendment + `local_hf` |
| `experiment0/run_experiment.py` | KeyboardInterrupt re-raise; incomplete-ledger fail-closed |
| `experiment0/episode_runner.py` | KeyboardInterrupt re-raise; BaseException not swallowed |
| `experiment0/tests/test_exp0_fault_recovery.py` | Amendment-aware FakeNimProvider |
| `experiment0/tests/test_exp0_http_pacing.py` | Align with enabled amendment |
| `experiment0/tests/test_exp0_prelaunch_ops.py` | Expect activated ops flags |
| `experiment0/tests/test_exp0_retry_amendment_v1.py` | Expect activated flags |
| `experiment0/tests/test_exp0_final_launch_gate.py` | **New** gate + dry-run suite |
| This report | Deliverable |

**Unchanged:** `config/experiment0_config.py`, Exp1 sources, prompts, metrics, frozen sampling, archived run.

---

## 3. Complete test results

| Suite | Result |
|---|---|
| Prior baseline | 233 passed |
| Final launch gate tests | **16 passed** |
| Full `experiment1/tests` + `experiment0/tests` | **249 passed** |
| Live NVIDIA / paid calls | **None** |
| Real N=60 schedule | **Not created** |

---

## 4. Frozen integrity results

| Check | Status |
|---|---|
| FROZEN_MANIFEST | **14/14** |
| TOTAL_TURNS / N=30+30 / C1–C2 | Unchanged |
| Actor/Witness temps, max_tokens, `enable_thinking=False` | Unchanged |
| Tokenizer qualification | **PASSED**, 7/7 Δ=0 |
| Revision | `2dc98e2afe4face0e4ce40972a915c45368bd34a` |
| Chat-template SHA-256 | `575fb74f54ed264df9047d0ecce3c98938aae953fb4f50356675706264cbb68a` |
| Archived `e0_20261007T132027Z` | Excluded + resume blocked |
| Actor/Witness isolation | Preserved (separate clients; Witness content not injected into Actor history by harness) |

---

## 5. Lifecycle dry-run results (mocks / temp dirs)

| Scenario | Result |
|---|---|
| Synthetic 60-slot schedule (tmp only) | 30 C1 + 30 C2, immutable, IDs bind once |
| Full 25-turn C1 episode | Completed |
| Full 25-turn C2 episode | Completed |
| Terminal HTTP 429 | Ops stop; 1 physical attempt; incomplete not marked complete |
| Partial quarantine + restart | Quarantine bak → full re-run → complete |
| Resume skip completed | `already_complete`, 0 extra HTTP |
| Witness JSON retries | Frozen path retained (prior amendment suite) |
| No scientific outcome peeking | Tests assert structure/ops only |

---

## 6. Terminal exception safety

| Case | Behavior |
|---|---|
| HTTP 429 / timeout | `TerminalOperationalError` → ops fail metadata; no Actor/Witness re-issue |
| `KeyboardInterrupt` | **Re-raised**; not classified as ops/429 stop |
| Unexpected `BaseException` | **Propagates**; not swallowed into failed-ops dict |
| Incomplete ledger after “success” return | Fail closed (`incomplete_ledger`) |
| No accidental continue after stop | Partial quarantined before any restart |

No control-flow gap requiring scientific-behavior changes was found.

---

## 7. Operator readiness

| Prerequisite | Status |
|---|---|
| `NIM_API_KEY` present in environment | **Yes** (value not logged) |
| Local disk free | **~68.9 GB** available |
| Host remain awake multi-day | **Operator must confirm** (sleep/hibernate not modified) |
| Retain existing ops/diagnostic logs | Safe to retain; no deletion performed |
| No conflicting live Exp0 inference | No launch performed this task; operator should confirm no other collector |
| Free-tier entitlement | **Not portal-verified** — same integrate free NIM path as prior screens; document uncertainty |

---

## 8. Unresolved limitations

- Free NIM rate limits remain opaque; screens ≠ multi-day guarantee.  
- Wall-clock still multi-day (~52 h pacing lower bound; realistic longer).  
- Capacity preflight still uses two live count calls at run start (paced); per-request counts are local_hf only.  
- Windows sleep / network / credential expiry remain operator risks.  
- Real randomized N=60 schedule **not** generated (by design).

---

## 9. Final scientific execution recommendation

**Engineering path is ready for a separate launch authorization.**

After operator confirms awake-host policy and free-tier risk acceptance, the next explicit command should be:

`NVIDIA_GO_FOR_CLEAN_N60`

That authorization alone should: create the **new** immutable N=60 schedule, start collection under the activated ops flags, never resume `e0_20261007T132027Z`, and keep outcome-blind stop/resume.

Until then: **do not** launch scientific inference.

---

## Integrity

- No live scientific inference  
- No real N=60 schedule  
- No archived-run resume  
- No outcome inspection  
- No OpenRouter/DeepInfra  
- No Git commits  

**STOP.** Await operator checks + `NVIDIA_GO_FOR_CLEAN_N60`.
