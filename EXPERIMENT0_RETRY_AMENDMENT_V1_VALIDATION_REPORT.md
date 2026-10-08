# Experiment 0 — Retry Amendment v1 Validation Report

**Date:** 2026-10-08  
**Decision input:** `RETRY_AMENDMENT_V1_CONDITIONALLY_APPROVED`  
**Activation flag:** `RETRY_AMENDMENT_V1_ENABLED = False` (unchanged — await final launch auth)  

---

## Verdict

# `RETRY_AMENDMENT_V1_READY_TO_ACTIVATE`

Complete-path validation passed under monkeypatched enablement. Scientific defaults and the live amendment flag remain **off**. Do not flip the flag or launch Exp0 until separate `NVIDIA_GO_FOR_CLEAN_N60` authorization.

---

## 1. Terminal exception propagation

| Layer | Behavior under amendment |
|---|---|
| `NimChatProvider._complete_amendment_v1` | Raises `TerminalOperationalError` for 429 / exhausted 5xx / ambiguous timeout |
| `NimAnthropicCompatClient.create` | Propagates without wrapping into retriable `Exception` |
| Actor `_call_api` / Witness `evaluate` | Catch only `Exception` — **cannot** retry `TerminalOperationalError` (`BaseException`) |
| `Experiment0EpisodeRunner.run` | Catches terminal ops → `EpisodeFailedError` with `failure_class` |
| `run_one_episode` | Returns `operational_stop`, `failure_class`, `amendment_id`; main writes `STOPPED_FOR_REVIEW` |
| Malformed Witness JSON | Remains `WitnessParseError` / `ValueError` — **not** terminal HTTP 429 |

Proven: `test_actor_outer_loop_cannot_retry_terminal_429` → exactly **1** paced HTTP attempt despite Actor’s 3-outer loop.

---

## 2. Physical-attempt budgets (tested)

| Failure class | Budget | Observed |
|---|---:|---|
| Persistent HTTP 429 | 1 | **1** attempt → terminal |
| Persistent HTTP 500 | ≤2 | **2** attempts → terminal |
| Ambiguous timeout | 1 | **1** attempt → terminal |
| 5xx then 200 | ≤2 | **2** attempts → success |
| Witness malformed JSON | frozen 3 | **3** Witness evaluate retries |
| All physical posts | paced | Through `GlobalHttpPacer` (≥60 s) |
| Hidden library retries | none | `urlopen` only; no Retry/HTTPAdapter |

---

## 3. Safe stop / resume (synthetic)

| Scenario | Result |
|---|---|
| 429 during Actor RAW | Operational fail + stop metadata |
| 429 during Witness RAW | Operational fail + stop metadata |
| 429 during Actor revision | Operational fail + stop metadata |
| 429 during Witness FINAL | Operational fail + stop metadata |
| Ambiguous timeout during generation | Operational fail (`ambiguous_timeout`) |
| Completed episodes | Remain committed / skip on resume |
| Partial episodes | Quarantine `*.partial_*.jsonl.bak` |
| No duplicate completed | `already_complete`, 0 extra HTTP |
| Immutable conditions | Slot dict unchanged after fail |
| Archived `e0_20261007T132027Z` | Resume blocked |
| Pause adaptation | No condition/outcome-based pacing |

---

## 4. Scientific integrity

| Item | Status |
|---|---|
| FROZEN_MANIFEST | **14/14** |
| TOTAL_TURNS = 25 | Unchanged |
| N = 30+30 | Unchanged |
| S1–S5 / prompts / sampling | Unchanged |
| Witness JSON retry policy | Unchanged |
| Buddhi / RAW–FINAL definitions | Unchanged |
| Experiment 1 sources | Untouched |
| `local_hf` | Not activated |
| `RETRY_AMENDMENT_V1_ENABLED` | **False** |

### Scientific implications (failure timing)

Enabling v1 **does not** alter measurements on successful episodes. It **does** change when an episode/run stops under provider throttle or transport failure (sooner, with fewer wasted HTTP posts). Completion probability for a multi-day N=60 is therefore an **operational** tradeoff, not a metric-definition change. Clean N=60 must not mix amended and non-amended policies.

---

## 5. Manifest provenance (ready)

`amendment_provenance()` records:

- `amendment_id` / `amendment_version`
- `enabled`
- Physical budgets by failure class
- Global pacing configuration
- Witness JSON policy note

`run_experiment` writes `manifest["ops"]["retry_amendment_v1"]` on new runs and `manifest["operational_stop"]` on terminal ops failures.

---

## 6. Files changed

| File | Role |
|---|---|
| `experiment0/retry_amendment.py` | `TerminalOperationalError`, budgets, provenance |
| `experiment0/engineering_config.py` | Budget constants; flag remains False |
| `experiment0/providers/nim_provider.py` | Frozen vs amendment complete/count paths |
| `experiment0/episode_runner.py` | Terminal ops catch |
| `experiment0/run_experiment.py` | Ops result + manifest fields |
| `experiment0/tests/test_exp0_retry_amendment_v1.py` | **New** validation suite |
| `experiment0/tests/test_exp0_http_pacing.py` | Expect TerminalOperationalError |
| Proposal + this report | Documentation |

---

## 7. Test results

| Suite | Count |
|---|---|
| Prior baseline | 212 passed |
| This validation | **233 passed** |
| Live NVIDIA / paid calls | **None** |
| Flag after tests | `RETRY_AMENDMENT_V1_ENABLED=False` |

---

## 8. Activation blockers (intentional)

1. Final `NVIDIA_GO_FOR_CLEAN_N60` not granted  
2. Flag deliberately False until that authorization  
3. `local_hf` not yet activated (separate approval)  
4. New N=60 schedule not created  

---

## Integrity

No Exp0 launch, no schedule, no hosted inference, no archived resume, no Git commit, no scientific outcome inspection, no OpenRouter.

**STOP.** Ready to activate only under final launch authorization.
