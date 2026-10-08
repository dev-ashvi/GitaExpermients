# Experiment 0 — P0 Engineering Implementation Report

**Date:** 2026-10-08  
**Authorization:** Minimal P0 engineering safeguards (MOCK_COVERAGE_GAPS_ONLY accepted)  
**Scientific launch:** Not performed (constraint honored)  
**External inference / paid APIs:** Not called  

---

## Final verdict

# `P0_ENGINEERING_GATES_PARTIALLY_CLOSED`

**Rationale:** Capacity hard-gate abstraction, Exp0 mock e2e, fault/recovery coverage, archival exclusion, and fail-closed resume/analysis guards are implemented and tested. Per-request **exact** token authorization still requires a provider-qualified counter (or an explicitly assessed `live_provider_count` mode); default scientific path fails closed rather than approximating. Nested retry amplification is measured and reported but **not** silently altered (frozen retry counts preserved). Alternate-provider (e.g. DeepInfra 262k) tokenization remains unqualified.

---

## 1. Files changed

| Path | Role |
|---|---|
| `EXPERIMENT0_ENGINEERING_GAP_AUDIT.md` | Corrected 262k arithmetic; archival status note |
| `experiment0/engineering_config.py` | **New** — engineering-only capacity/archival settings |
| `experiment0/capacity_gate.py` | **New** — provider-context gate + gating client |
| `experiment0/archival.py` | **New** — additive archival + fail-closed guards |
| `experiment0/capacity.py` | Wire gate; profile-aware preflight |
| `experiment0/run_experiment.py` | Per-request capacity wrap; archival resume block |
| `experiment0/analyze.py` | Fail-closed clean-analysis block for archived runs |
| `experiment0/runs/e0_20261007T132027Z/ARCHIVAL_MANIFEST.json` | **New** additive archival record |
| `experiment0/tests/test_exp0_capacity_gate.py` | **New** boundary tests |
| `experiment0/tests/test_exp0_mock_e2e.py` | **New** synthetic C1/C2 e2e |
| `experiment0/tests/test_exp0_fault_recovery.py` | **New** fault/recovery + amplification |
| `EXPERIMENT0_P0_ENGINEERING_IMPLEMENTATION_REPORT.md` | This report |

**Not modified (scientific protocol / Exp1):**  
`config/experiment0_config.py`, Experiment 1 sources, prompts, rubric, metrics, sampling, Witness 1600, frozen retries, conditions, N=30+30, S1–S5, schedule of aborted run.

---

## 2. New tests

| Module | Coverage |
|---|---|
| `test_exp0_capacity_gate.py` | 1M pass; 262144 provisional arithmetic; exact threshold; +1 over threshold; unknown limit; unverified counts; gating client role budget; unavailable/unverified counters |
| `test_exp0_mock_e2e.py` | C1 with revision; C2 without; obstruction identity; isolation; episode-boundary reset; partial unsafe resume; temp non-scientific ledgers |
| `test_exp0_fault_recovery.py` | HTTP 429/500/timeout; malformed Witness JSON; retry amplification (=9); partial quarantine; resume skip; schedule immutability; archival guards; real aborted-run exclusion; analyze CLI block |

---

## 3. Existing tests preserved

| Suite | Result |
|---|---|
| Experiment 1 (`experiment1/tests`) | **113 passed**, 0 failed, 0 skipped |
| Experiment 0 prior + new (`experiment0/tests`) | **55 passed**, 0 failed, 0 skipped |
| Combined | **168 passed**, 0 failed, 0 skipped |
| Frozen manifest | **14/14** OK |

Baseline before this pass was 143 (30 Exp0 + 113 Exp1). New engineering tests add 25 (55−30).

---

## 4. Capacity-gate design

### Rules enforced

1. Frozen **85%** fraction (`prompt_tokens + reserved_output ≤ 0.85 × context`).
2. Context limit comes from a **named provider profile** (`engineering_config.PROVIDER_CONTEXT_PROFILES`) — not a universal hardcoded 1M for all providers.
3. `context_limit_verified=False` or missing limit → **fail closed** (`CapacityConfigurationError`).
4. Token trust must be `VERIFIED`; `UNVERIFIED` / `UNAVAILABLE` / `None` → **fail closed** (`CapacityGateError`).
5. Per-request check wraps Anthropic-shaped `messages.create` via `CapacityGatingAnthropicClient` immediately before each Actor/Witness generation (including revisions / re-evals), using the **exact** serialized `system`+`messages` and the call’s `max_tokens` as the role output budget.
6. No silent truncation, summarization, or prompt mutation.
7. Default scientific mode: `PER_REQUEST_TOKEN_COUNT_MODE = "unavailable"` — **no** approximate authorization and **no** extra live token-count API calls on the execution path (rate-limit risk assessed below).
8. Optional `live_provider_count` mode exists but is **off** by default.
9. NVIDIA preflight (`run_capacity_preflight`) still uses provider-exact `usage.prompt_tokens` for worst-case Actor/Witness against the active verified profile (`nvidia-nim` @ 1M).

### Profiles

| Profile | Limit | Verified? |
|---|---|---|
| `nvidia-nim` | 1_000_000 | Yes (NIM hosting claim) |
| `deepinfra-262k` | 262_144 | **No** (window candidate only) |
| `unknown` | None | No |

### Audit arithmetic correction (preserved)

- \(262{,}144 \times 0.85 = 222{,}822.4\)
- Actor: \(207{,}876 + 800 = 208{,}676\) → provisionally fits
- Witness: \(170{,}414 + 1{,}600 = 172{,}014\) → provisionally fits  
These remain **NVIDIA-derived**, not DeepInfra-verified — they do **not** qualify that backend.

---

## 5. Isolation assertions

Synthetic e2e verifies Actor API payloads do not contain Witness rubric instructions, `overall_score`, `witness_raw`, structured `"verdict"`, or `experimental condition`. Buddhi feedback path retains existing Actor isolation checks. Exp1 actor/witness/episode sources unchanged (hashes verified).

---

## 6. Retry-amplification findings

Frozen counts (unchanged):

- `API_MAX_RETRIES = 3` (Actor outer loop; Witness evaluate outer loop)
- `NimChatProvider.max_retries = 3` (inner HTTP attempts)
- `API_RETRY_BASE_DELAY_SEC = 1.0` (backoff policy unchanged)

**Measured maximum underlying API attempts for one Actor.generate under persistent 429:**

\[
3 \times 3 = 9
\]

(Actor outer × provider inner). Confirmed by `test_retry_amplification_max_underlying_attempts` (`http_attempts == 9`).

Witness HTTP failures similarly nest up to **9** attempts per `evaluate()` call. Malformed Witness JSON (HTTP 200) retries up to **3** parse/API outer attempts without provider inner amplification on success.

### Proposed infrastructure amendment (NOT applied)

Nested ownership of retries (Actor/Witness **and** provider) multiplies load and worsens rate-limit pressure. Proposal for a future engineering change (requires explicit approval; must not silently change frozen scientific retry policy mid-study):

- Single retry owner (provider **or** Actor/Witness, not both), **or**
- Cap total underlying attempts per logical call while documenting the new policy as an engineering amendment.

---

## 7. Archival record and exclusion guard

| Field | Value |
|---|---|
| Run ID | `e0_20261007T132027Z` |
| Label | `ABORTED_OPERATIONAL_RATE_LIMIT_PRE_ANALYSIS` |
| Manifest | `experiment0/runs/e0_20261007T132027Z/ARCHIVAL_MANIFEST.json` (additive) |
| Completed episodes | 19 / 60 |
| Scientific inspection | **None** (Actor/Witness scientific fields not read) |
| Excluded from clean N=60 | **Yes** |
| Original ledgers/schedule/hashes | **Preserved** (not overwritten/deleted) |
| Replacement schedule | **Not created** |
| Resume | Blocked (`assert_not_archived_for_resume` + exclusion list) |
| Clean analysis | Blocked (`assert_allowed_for_clean_analysis` / analyze CLI exit 3) |

---

## 8. Frozen artifact integrity

### Before → after (scientific / Exp1 critical)

| Artifact | SHA-256 | Status |
|---|---|---|
| `config/experiment0_config.py` | `12d02f15…06910b` | **Unchanged** |
| `experiment1/config/experiment_config.py` | `14d42aa2…3d50ac` | **Unchanged** |
| `experiment1/src/actor.py` | `d0ed9dd1…badbb6` | **Unchanged** |
| `experiment1/src/witness.py` | `644daf98…72590f` | **Unchanged** |
| `experiment1/src/episode_runner.py` | `078fdb1a…bd7cf2` | **Unchanged** |
| `experiment1/src/buddhi.py` | `56b06f53…9ea5b4` | **Unchanged** |
| `experiment1/src/script_loader.py` | `c54f9992…fe5bbd3d` | **Unchanged** |
| FROZEN_MANIFEST | 14/14 | **OK** |

Engineering changes are isolated in `experiment0/engineering_config.py` and related Exp0 harness modules.

---

## 9. Remaining provider qualification requirements

1. **Per-request exact token counter** for the scientific path: qualify a local tokenizer matching the target provider template, **or** explicitly enable `PER_REQUEST_TOKEN_COUNT_MODE = "live_provider_count"` after accepting rate-limit/cost doubling (not recommended given prior 429 history).
2. **DeepInfra / OpenRouter / 262k backends:** re-measure Actor/Witness worst-case with **that** provider’s tokenizer; do not reuse NVIDIA counts. Profile `deepinfra-262k` remains fail-closed until `context_limit_verified=True` **and** tokens are re-verified.
3. `enable_thinking=False` mapping fidelity on non-NIM OpenAI-compatible backends.
4. Backend pin / no silent model fallback (still not implemented — out of P0 scope).

---

## 10. Unresolved blocker

| Blocker | Severity | Notes |
|---|---|---|
| Default per-request token mode `unavailable` | **Operational** for next clean N=60 | Fail-closed by design until a verified counter is injected or live count is explicitly approved |
| Nested retry amplification (max 9 HTTP / logical Actor call) | **Operational** | Reported; frozen counts not changed |
| Clean N=60 collection | **Not started** | Requires new run (not a resume of archived run); no schedule created yet |

No protocol-integrity blocker. No scientific artifact corruption.

---

## Test counts (exact)

```
Experiment 1:     113 passed, 0 failed, 0 skipped
Experiment 0:      55 passed, 0 failed, 0 skipped
Combined:         168 passed, 0 failed, 0 skipped
FROZEN_MANIFEST:   14/14 OK
```

---

## Strict stop

Stopped after implementation and testing. Did **not**: launch experiments, resume archived run, call external inference APIs, install Ollama, add scientific models, change scientific prompts/outcomes, create a replacement N=60 schedule, initialize Git, commit, or begin OpenRouter migration.
