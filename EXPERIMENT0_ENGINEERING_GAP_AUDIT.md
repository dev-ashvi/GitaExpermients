# Experiment 0 Engineering Readiness Gap Audit

**Date:** 2026-10-08  
**Mode:** Read-only (no protocol edits, no API calls, no ledger mutation, no resume)  
**Agreed direction:** MOCK FIRST — LOCAL GPU OPTIONAL  

---

## Executive verdict

**`MOCK_COVERAGE_GAPS_ONLY`**

The frozen scientific protocol and Experiment 1 integrity remain intact. The **143-test baseline still holds** (113 + 30). Harness-level Actor/Witness isolation and Exp1 mock episode machinery are strong.

What is **not** yet sufficient for a clean paid N=60 run:

1. Experiment 0’s **live execution path** (`Experiment0EpisodeRunner` + `NimAnthropicCompatClient` + `run_experiment.py`) lacks dedicated end-to-end mock / fault-injection coverage.
2. Capacity enforcement is **preflight-only**, tied to **1,000,000** context and **live NIM token counting** — a smaller OpenAI-compatible window (e.g. advertised 262,144) is not offline-gated.
3. Nested retries (provider + Actor + Witness) can **amplify** HTTP 429 load; behavior is operationally safe (stop / quarantine / resume) but not mock-proven for Exp0.
4. Aborted run `e0_20261007T132027Z` is still `STOPPED_FOR_REVIEW` with **no permanent archival label**; no Git freeze tag exists (repo has no `.git`).

No scientific outcomes were inspected. No artifacts were modified except this report file.

---

## A. Current repository inventory

### Experiment 0 — execution & providers

| Component | Path | Notes |
|---|---|---|
| Config | `config/experiment0_config.py` | Model IDs, temps, max_tokens (Actor 800 / Witness 1600), N=30+30, capacity 0.85×1M, obstruction strings |
| Config loader | `experiment0/_e0_config.py` | File-path import avoids shadowing Exp1 `config` package |
| Provider contract | `experiment0/providers/base.py` | `ProviderRequest`, `NormalizedLLMResponse`, `ProviderError`, `LLMProvider` |
| NIM adapter | `experiment0/providers/nim_provider.py` | `NimChatProvider.complete`, `count_prompt_tokens`, 429/5xx retry, `NimAnthropicCompatClient` |
| Anthropic wrapper | `experiment0/providers/anthropic_provider.py` | Optional uniform interface; Exp1 still uses Anthropic SDK directly |
| Script loader | `experiment0/script_loader.py` | `Experiment0ScriptLoader` — Exp1 prompts; Exp0 shared T15–24 responses |
| Episode runner | `experiment0/episode_runner.py` | `Experiment0EpisodeRunner` — turn loop, Buddhi, OSM, ledger |
| Orchestrator | `experiment0/run_experiment.py` | Integrity gate, capacity, immutable schedule, resume, quarantine, ops-only progress |
| Capacity | `experiment0/capacity.py` | Worst-case Actor/Witness requests; `evaluate_capacity`; live NIM preflight |
| Metrics | `experiment0/metrics.py` | RCVR / BUD / Alignment / terminal decision (post-run only) |
| Analysis | `experiment0/analyze.py` | Post-run integrity + science (**must not run on aborted incomplete set as clean N=60**) |
| Calibration | `experiment0/witness_calibration.py`, `run_calibration.py` | Live Witness fixture discrimination |

### Experiment 1 — frozen harness reused by Exp0

| Component | Path |
|---|---|
| Actor | `experiment1/src/actor.py` — isolation scan, history commit, revision path |
| Witness | `experiment1/src/witness.py` — JSON schema parse, isolation labels, retries |
| Buddhi | `experiment1/src/buddhi.py` — obstruction only T15–24 + UP-1 |
| OSM | `experiment1/src/osm.py` — logged; does not drive Buddhi |
| ICM | **No separate ICM module** — not present as `icm.py` |
| Ledger | `experiment1/src/karma_ledger.py` — append-only JSONL, duplicate-turn guard |
| Exp1 runner | `experiment1/src/episode_runner.py` — fail-and-restart mid-episode |
| Integrity | `experiment1/src/types_util.py` — `validate_input_integrity`, `FROZEN_MANIFEST` |
| Config | `experiment1/config/experiment_config.py` |

### Tests & mocks

| Area | Path |
|---|---|
| Exp1 mock client | `experiment1/tests/conftest.py` — `MockAnthropic`, responders |
| Exp1 isolation | `test_actor_isolation.py`, `test_witness_isolation.py` |
| Exp1 full episode | `test_episode_invariants.py`, `test_obstruction_reeval.py`, `test_condition_diffs.py` |
| Exp1 fail/restart | `test_fail_restart.py`, partial-resume `UnsafeResumeError` test |
| Exp0 tests | `experiment0/tests/test_exp0_*.py` (30 tests) — metrics, injection, capacity rule, provider payload, Exp1 hash preservation |
| Diagnostics (non-science) | `diagnostics/nim_large_context_rate_limit*.py`, operational cost audit |

### Docs / amendments

- `docs/experiment0_scope_v1.0.md`
- `docs/experiment0_instrumentation_amendment_v1.0.1.md` (Witness 600→1600)
- `docs/experiment0_opposite_direction_clarification_v1.0.2.md`

---

## B. Test baseline

Executed from repo root (read-only; no snapshot updates):

| Suite | Discovered | Result |
|---|---:|---|
| Experiment 0 `experiment0/tests` | 30 | **30 passed** |
| Experiment 1 `experiment1/tests` | 113 | **113 passed** |
| **Combined** | **143** | **143 passed** |

- Failed: 0  
- Skipped: 0  
- Environment failures: none  

**Baseline still holds: 143 PASS.**

These unit/integration tests use mocks/fixtures only; they do not write into `e0_20261007T132027Z`.

---

## C. Coverage matrix

| Capability | Status | Evidence |
|---|---|---|
| Valid Actor response (mock) | **Covered** (Exp1) | `MockAnthropic` + episode invariants |
| Valid Witness JSON | **Covered** (Exp1) | `test_witness_accepts_valid_json` |
| Witness REJECT / REVISE | **Covered** (Exp1) | obstruction / UP-1 fixtures |
| Malformed / truncated Witness JSON | **Covered** (Exp1) | `WitnessParseError` after retries |
| HTTP 429 fault injection | **Missing** (Exp0 path) | NIM retries real 429s; no unit test injects 429 into `NimChatProvider` / Exp0 resume |
| HTTP 500 | **Partial** | Retried in `NimChatProvider`; no Exp0 mock test |
| Timeout | **Missing** | No dedicated timeout fault test |
| Provider backend change detection | **Missing** | `model_id_returned` logged in `provider_meta`; not asserted as pin |
| Interrupted episode | **Partial** | Exp1 `UnsafeResumeError`; Exp0 quarantine+restart in `run_experiment.py` — **no Exp0 automated test** |
| Resume without duplicating completed episodes | **Partial** | Implemented (`episode_complete` skip); exercised operationally; **no Exp0 unit test** |
| C1/C2 condition injection | **Covered** (Exp0) | `test_exp0_condition_injection.py` |
| T15–24 identical C1/C2 | **Covered** (Exp0) | obstruction + injection tests |
| Capacity 0.85 rule (offline arithmetic) | **Covered** | `test_exp0_capacity_rule.py` |
| Capacity with live tokenizer | **Partial** | Live NIM only; not mockable offline |
| Mid-episode capacity re-check | **Missing** | Preflight once per process start/resume |
| Actor isolation (harness) | **Covered** (Exp1) | extensive `test_actor_isolation.py` |
| Witness isolation (harness) | **Covered** (Exp1) | `test_witness_isolation.py` |
| Exp0 runner isolation regression | **Missing** | No test that Exp0 dual `NimAnthropicCompatClient` never cross-wires system prompts |
| Buddhi routing | **Covered** (Exp1) | `test_buddhi.py`, obstruction reeval |
| OSM sequencing | **Partial** | OSM runs; logged; no ICM |
| Ledger integrity | **Covered** (Exp1) | `test_karma_ledger.py` |
| Exp1 frozen hashes | **Covered** (Exp0) | `test_exp1_preservation.py` — hashes OK this audit |
| FROZEN_MANIFEST 14/14 | **Covered** | `validate_input_integrity()` OK |
| Terminal metrics logic | **Covered** (Exp0) | Cases A–D opposite-direction tests |
| Nested retry amplification | **Missing** as test | Present in code (provider × Actor × Witness) |
| Separate local HTTP mock server | **Not needed for most gaps** | Inject `MockAnthropic` / fake `NimChatProvider.complete` |

---

## D. Isolation assessment

### Harness-level (auditable — strong)

- Actor system prompt = task framing + constitution + sources only; scanned by `validate_actor_system_prompt` / leakage patterns.
- Witness request = source packet + user turn + agent output + protocol/instructions; structural label checks block CONDITION/PHASE/TURN/OSM/BUDDHI injection.
- Buddhi feedback is the **only** authorized Witness-derived Actor input on revision; tests forbid score/verdict leakage in feedback.
- Exp0 constructs **separate** `Actor` and `Witness` objects with **separate** `NimAnthropicCompatClient` wrappers (same underlying `NimChatProvider` transport).
- Episode starts require empty Actor history; partial resume with empty history raises `UnsafeResumeError`.

### Provider-level (not provable from Python alone)

- Hosted backends may share infrastructure, caches, or routing across requests.
- Cannot prove absence of hidden cross-request state between Actor and Witness calls.
- **Mitigation for next run:** pin provider/backend, log `model_id_returned` / request IDs, disable multi-provider fallback if using a router — qualify before science.

### Gaps

- No Exp0-specific test that RAW vs revision Actor payloads exclude Witness rubric when driven through `Experiment0EpisodeRunner`.
- `provider_meta` overwrites last call per turn (Witness typically) — fine for ops, not an isolation proof.

---

## E. Context / provider readiness

### Established (NVIDIA hosted, prior work)

| Item | Value |
|---|---|
| Actor worst-case prompt (provider count) | ~207,876 |
| Actor `max_tokens` | 800 |
| Witness worst-case prompt | ~170,414 |
| Witness `max_tokens` | 1600 |
| Capacity rule | `prompt + reserved_out ≤ 0.85 × context` |
| Configured context | **1,000,000** (`MODEL_CONTEXT_LIMIT`) |
| Preflight | Live NIM `usage.prompt_tokens` at run start |

### Not established / risks

| Item | Risk |
|---|---|
| OpenRouter / DeepInfra **262,144** window | See **CORRECTION** below. Arithmetic fit is provisional; **tokenization is not DeepInfra-verified**. Provider qualification still required before that backend. |
| Tokenizer mismatch | Counting is provider-specific NIM usage; switching providers without re-measure can mis-gate |
| Mid-episode growth | History grows; only worst-case preflight at start — no per-turn gate |
| `enable_thinking=False` | Sent as `chat_template_kwargs` on NIM; OpenAI-compatible mapping must be re-verified per provider |
| Backend pin / no fallback | Not implemented for OpenRouter-style routers |

### CORRECTION (2026-10-08) — 262,144 capacity arithmetic

The audit draft incorrectly stated that the prior Actor token estimate exceeds 85% of a 262,144-token context.

Correct arithmetic:

- \(262{,}144 \times 0.85 = 222{,}822.4\)
- Actor: \(207{,}876 + 800 = 208{,}676\) → **provisionally fits** (\(\le 222{,}822\))
- Witness: \(170{,}414 + 1{,}600 = 172{,}014\) → **provisionally fits**

**Important:** These are **NVIDIA-derived** `usage.prompt_tokens` counts, **not** verified DeepInfra (or other provider) counts. Provisional arithmetic fit **does not** establish provider qualification. Tokenizer/template differences can change the measured prompt size; re-measure on the target provider before authorizing scientific traffic.

### Offline vs live qualification

| Check | Offline? |
|---|---|
| 0.85 arithmetic with assumed limits | Yes |
| Exact provider tokenization | **No** — needs provider |
| Thinking-disable fidelity | **No** — needs provider probe |
| Latency / 429 behavior under load | **No** — needs provider (diagnostics already informal) |

**Do not call paid/hosted endpoints in this audit (constraint honored).**

---

## F. Previous run preservation (operational only)

| Field | Value |
|---|---|
| Run ID | `e0_20261007T132027Z` |
| Status | **`STOPPED_FOR_REVIEW`** |
| Completed episodes | **19** (indices 0–18) |
| Scientific analysis | **None** (`analysis_report.json` absent) |
| Permanent archival label | Applied in P0 engineering pass: `ABORTED_OPERATIONAL_RATE_LIMIT_PRE_ANALYSIS` via additive `ARCHIVAL_MANIFEST.json` (see P0 implementation report) |
| Ledger / schedule / manifest | Present under `experiment0/runs/e0_20261007T132027Z/` |
| Stop cause (ops) | HTTP 429 after frozen retries (documented in ops log / stop_reason) |

**Status update:** archival exclusion + fail-closed resume/analysis guards are implemented in the P0 engineering pass (additive; original ledgers preserved).

No Witness scores, RCVR/BUD/Alignment, or condition-wise outcomes were read for this section.

---

## G. Ranked engineering gaps

### P0 — Must address before any clean scientific run

1. **Offline capacity hard-gate** parameterized by configured context limit (fail closed if worst-case Actor/Witness cannot fit 0.85×window) — prevents accidental start on a too-small backend.
2. **Exp0 end-to-end mock episode** through `Experiment0EpisodeRunner` + `Experiment0ScriptLoader` (25 turns, C1 and C2, tmp ledger) — proves sequencing / injection / RAW–FINAL / completion without live inference.
3. **Formal preserve/exclude policy** for `e0_20261007T132027Z` (archival label + documented exclusion from clean N=60) — process/control, not code science.
4. **Fault-injection: 429 → retry exhaustion → STOPPED_FOR_REVIEW → resume skips completes** on Exp0 orchestrator with fake provider — locks the recovery contract that already exists in code.

### P1 — Must qualify before paid execution

1. Provider-specific token measure + capacity preflight on the **chosen** paid endpoint.
2. Pin model ID / disable silent multi-backend failover; log backend identity.
3. Map/verify `enable_thinking=False` (or equivalent) on that API.
4. Measure sustained large-context pacing needs for that endpoint (prior NIM diagnostics are informative only for NIM).
5. Confirm Witness `max_tokens=1600` completes structured JSON on that backend (calibration-equivalent).

### P2 — Useful engineering

1. Per-turn or rolling capacity check as history grows.
2. Reduce nested retry amplification (without changing scientific thresholds) — e.g. clearer ownership of retry layer — **only after mock proof; do not silently change frozen retry counts mid-study**.
3. Persist full HTTP headers on 429 for ops.
4. Exp0 unit tests for quarantine naming and schedule immutability.
5. Initialize Git + freeze tag **after approval**.

### P3 — Optional

1. Local GPU / Ollama path (explicitly optional; 12 GB VRAM unlikely for 120B full-precision).
2. Standalone HTTP mock server (unnecessary if client injection covers gaps).
3. ICM module (not in current architecture; OSM only).

---

## H. Minimal implementation proposal (do not implement yet)

Smallest set before provider qualification:

1. **Offline capacity assert** in `run_experiment` preflight using configured `MODEL_CONTEXT_LIMIT` + known worst-case token estimates (or last measured counts), failing before any episode if Actor/Witness cannot fit.
2. **One Exp0 mock e2e test module** injecting `MockAnthropic` (or a tiny fake `complete()`) into Actor/Witness via the same construction as `run_one_episode`, writing to `tmp_path`, asserting 25 turns and C1/C2 injection — **never** writing under `e0_20261007T132027Z`.
3. **One Exp0 recovery test**: fake provider raises 429 until retries exhaust → orchestrator marks stop; second call with `--resume-run-id` skips completed ledgers.
4. **Archival doc/label** for the aborted run (metadata only).

Then: **provider qualification harness** (separate from science) against the paid endpoint.

---

## I. Explicit non-goals (do not build yet)

- OpenRouter production adapter / paid scientific episodes  
- Local 120B GPU serving / Ollama install  
- New HTTP mock server  
- Changing N, conditions, metrics, thresholds, prompts, sources  
- Modifying Experiment 1  
- Changing frozen retry counts mid-flight for the aborted run  
- Incorporating the 19 completed episodes into a clean N=60 analysis  
- Scientific analysis of `e0_20261007T132027Z`  
- Git commit/tag without approval  
- Further pacing-interval exploration as a substitute for mocks  

---

## J. Final verdict

# `MOCK_COVERAGE_GAPS_ONLY`

**Rationale:** Protocol integrity and the 143-test baseline are healthy; Exp1 mock depth is high; Exp0 live-path mock/fault and offline capacity gating for alternate context windows are the material gaps. Not a protocol-integrity failure; not ready to skip mock work and jump straight to paid qualification without the P0 items above.

**Stop.** Await approval before implementing any of the proposed changes.
