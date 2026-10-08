# Experiment 0 — NVIDIA Scientific Pre-Launch Readiness Report

**Date:** 2026-10-08  
**Authorization:** `NVIDIA_GO_FOR_PRELAUNCH_PREPARATION`  
**Not authorized:** `NVIDIA_GO_FOR_CLEAN_N60` / scientific collection / schedule creation  

---

## Verdict

# `NVIDIA_PRELAUNCH_READY_PENDING_AMENDMENT`

Engineering safeguards for paced NVIDIA collection are **implemented and tested**. Launch remains blocked pending:

1. Explicit decision on **retry amendment v1** (approve **or** formally keep frozen 3×3 under pacing),  
2. Explicit approval to activate **`local_hf`** token counting for the scientific path,  
3. Explicit **`NVIDIA_GO_FOR_CLEAN_N60`** plus new immutable N=60 schedule generation.

Endurance screens **do not** guarantee an uninterrupted N=60.

---

## 1. Files changed

| File | Change |
|---|---|
| `experiment0/http_pacing.py` | **New** — `GlobalHttpPacer`, `FakeClock`, persisted state, attempt log, fail-closed clock/state errors, exclusive lock |
| `experiment0/retry_amendment.py` | **New** — amendment helpers; inactive unless flag True |
| `experiment0/engineering_config.py` | Pacing constants; `RETRY_AMENDMENT_V1_ENABLED=False`; `PRELAUNCH_RECOMMENDED_TOKEN_COUNT_MODE=local_hf` (not activated) |
| `experiment0/providers/nim_provider.py` | Pace at `_post_json`; optional amendment hooks; purpose/role on compat client |
| `experiment0/run_experiment.py` | `build_nim_http_pacer`; attach pacer before preflight; purpose=actor/witness; ops manifest fields |
| `experiment0/tests/test_exp0_http_pacing.py` | **New** pacing / concurrency / restart / retry-paced / amendment-disabled tests |
| `experiment0/tests/test_exp0_prelaunch_ops.py` | **New** integrity, local_hf readiness, 429/quarantine/resume, archival, capacity |
| `EXPERIMENT0_NVIDIA_RETRY_AMENDMENT_PROPOSAL.md` | Formal amendment proposal (not applied) |
| `EXPERIMENT0_NVIDIA_PRELAUNCH_READINESS_REPORT.md` | This report |

**Unchanged (scientific):** `config/experiment0_config.py`, Exp1 sources/prompts/metrics/sampling, frozen retry **counts**, archived run ledgers.

---

## 2. Tests

| Suite | Result |
|---|---|
| New pacing + prelaunch tests | **23 passed** |
| Full `experiment0/tests` + `experiment1/tests` | **212 passed** |
| Live inference in tests | **None** |

Coverage includes: global pacing Actor/Witness; pacing across retries; process restart wall restore; concurrent-call prevention; corrupt/future clock fail-closed; HTTP 429 episode fail + partial quarantine; resume skip completed; archival exclusion; provider identity field; qualified `local_hf` capacity; frozen hash preservation; no scientific metrics in ops progress; amendment disabled by default.

---

## 3. Frozen hashes / integrity recheck

| Check | Status |
|---|---|
| FROZEN_MANIFEST | **14/14** |
| Exp1 preservation tests | Pass |
| Tokenizer revision | `2dc98e2afe4face0e4ce40972a915c45368bd34a` |
| Chat-template hash | `575fb74f54ed264df9047d0ecce3c98938aae953fb4f50356675706264cbb68a` |
| NIM qualification | **PASSED**, 7/7 probes Δ=0 |
| Provider profile | `nvidia-nim`, context **1,000,000**, fraction **0.85** |
| Archived run | `e0_20261007T132027Z` excluded + resume blocked |
| Actor/Witness isolation | Unchanged (separate clients; Witness content not written into Actor history by harness) |
| Buddhi / RAW–FINAL / 25-turn script / C1–C2 / S1–S5 / N=30+30 | Unchanged scientific config |
| `PER_REQUEST_TOKEN_COUNT_MODE` | Remains **`unavailable`** (default) |
| `PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED` | **False** |

---

## 4. Global HTTP pacing guarantees

| Guarantee | Mechanism |
|---|---|
| ≥60 s start-to-start | `GlobalHttpPacer` + `NIM_HTTP_MIN_START_TO_START_SEC=60` |
| All Actor / Witness / revisions / retries / count posts | Enforced in `NimChatProvider._post_json` only |
| No concurrent NIM HTTP | Process `RLock` held for entire attempt |
| No catch-up overlap | Next start scheduled from prior **actual** start; long calls delay the next start |
| Monotonic in-process | `time.monotonic` (injectable `FakeClock` in tests) |
| Restart-safe | Persisted `last_attempt_start_unix` under `experiment0/runs/_nim_ops/` |
| Fail closed | Corrupt / future / missing-field state → `PacingError` |
| Audit | `nim_http_attempts.jsonl` (timestamps, role, purpose, latency, status — **no** message bodies) |

Enabled by default for scientific `run_experiment.main` (`NIM_HTTP_PACING_ENABLED=True`).

---

## 5. Recovery behavior (current, amendment off)

| Event | Behavior |
|---|---|
| HTTP 429 | Frozen nested retries up to 9 paced HTTP attempts per logical Actor call; then episode fail → `STOPPED_FOR_REVIEW` |
| Partial episode | Quarantine `*.partial_*.jsonl.bak`; restart same schedule slot |
| Completed episode | Skip on resume (`already_complete`) |
| Archived 19/60 | Resume / clean analysis **blocked** |
| Amendment v1 | **Disabled** — see companion proposal |

---

## 6. `local_hf` preparation (not activated)

Verified ready for a **future** flip:

- Pinned HF revision + on-disk hashes  
- Chat-template hash match  
- Evidence `PASSED` / 7× Δ=0 / `nvidia-nim`  
- Gate: 1M × 0.85  
- Tests: nvidia-nim authorizes VERIFIED counts; unverified profiles fail closed  
- Once activated: **no** extra live count HTTP calls (`LocalNemotronChatTokenCounter` only)

**Still required for activation:** set `PER_REQUEST_TOKEN_COUNT_MODE="local_hf"` and `PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED=True` under separate approval (not done here).

---

## 7. Time and scheduling estimates

Assumptions: ~**3,107** physical inference HTTP attempts; ≥60 s between starts; Witness durations from generation screen (~45–78 s, often >60 s late in the session).

| Estimate | Value |
|---|---|
| Pacing-only lower bound | **~51.8 h** (3107 × 60 s) |
| Realistic continuous (no long pauses) | **~55–70 h** wall-clock (Witness overruns + Actor waits) |
| With ops pauses / sleep / reconnect | **Multi-day (3–5+ calendar days)** typical planning envelope |

**52 hours is a lower bound, not a completion SLA.**

### Risks and safeguards

| Risk | Safeguard |
|---|---|
| Multi-day model/backend drift | Immutable schedule; record `model` / request ids; same provider profile; no mid-run model swap |
| Machine restart | Persisted pacing state; resume skip completes; quarantine partials |
| Windows sleep | Disable sleep/hibernate for collection host; UPS if possible |
| Internet interruption | `STOPPED_FOR_REVIEW`; resume after ops fix; pacing restore |
| Expired credentials | Pre-launch key check; stop on auth errors (non-retriable) |
| Quota / 429 | Ops stop; optional amendment v1; no outcome-adaptive pacing |
| Condition/time confounding | Process schedule order only; condition-blind pauses; analyze after full freeze |

**Do not create the real N=60 schedule until `NVIDIA_GO_FOR_CLEAN_N60`.**

---

## 8. Pre-launch checklist

| # | Item | Status |
|---|---|---|
| 1 | Frozen protocol integrity (14/14, Exp1 untouched) | **Ready** |
| 2 | Operational pacing (≥60 s, shared transport, persisted) | **Ready** |
| 3 | Retry amendment status | **Pending decision** (proposal filed; flag False) |
| 4 | Tokenizer / `local_hf` activation | **Prepared, not activated** |
| 5 | Provider identity `nvidia/nemotron-3-super-120b-a12b` | **Ready** |
| 6 | Archival exclusions | **Ready** |
| 7 | Immutable schedule generation process | **Ready code; schedule not created** |
| 8 | Outcome-blind stop/resume | **Ready** (tested synthetically) |
| 9 | Credential readiness (`NIM_API_KEY`) | **Operator check at launch** |
| 10 | New run provenance / reproducibility | **Ready** (manifest ops block) |
| 11 | Logging + disk space | **Attempt JSONL + ledgers; operator verify free disk** |
| 12 | Final GO/NO-GO | **NO-GO until clean-N60 approval** |

---

## 9. Settings still requiring approval

| Setting | Current | Needs |
|---|---|---|
| `RETRY_AMENDMENT_V1_ENABLED` | `False` | Approve amendment **or** accept frozen 3×3 under pacing |
| `PER_REQUEST_TOKEN_COUNT_MODE` | `unavailable` | Approve flip to `local_hf` |
| `PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED` | `False` | Set True when mode flipped |
| New N=60 `assignment_schedule.json` | Not created | `NVIDIA_GO_FOR_CLEAN_N60` |
| Scientific collection start | Not started | Same |

---

## 10. Explicit launch blockers

1. No `NVIDIA_GO_FOR_CLEAN_N60` authorization.  
2. No new immutable schedule (by design).  
3. Retry policy decision unresolved (amendment vs frozen amplification).  
4. Scientific token mode still `unavailable` (capacity per-request would fail closed if collection started without `local_hf` or injected counter — **activate `local_hf` before launch**).  
5. Operator environment: disable sleep, confirm disk, confirm free-tier entitlement / key.

---

## 11. Remaining concerns

- Free-tier policy remains opaque; screens ≠ multi-day guarantee.  
- Nested frozen retries under pacing can still spend **many hours** inside a single throttled logical call if amendment is declined.  
- Capacity preflight still uses live `count_prompt_tokens` (2 paced calls) at start — acceptable; per-request live counts must stay off.  
- Windows host sleep is an operational hazard outside code control.

---

## Integrity statement

- Experiment 0 **not** launched  
- No new N=60 schedule  
- Archived run **not** resumed  
- No hosted inference during this task  
- No OpenRouter / Git init / commit  
- No scientific outcome inspection  
- Frozen prompts / sources / metrics / sampling **unchanged**  
- Retry amendment **not** auto-adopted  

**STOP.** Await approval before schedule creation or scientific collection.
