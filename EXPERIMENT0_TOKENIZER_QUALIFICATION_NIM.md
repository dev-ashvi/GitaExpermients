# Experiment 0 — Stage B: NVIDIA NIM Tokenizer Qualification

**Date:** 2026-10-08  
**Scope:** Engineering token-count equivalence only (not Experiment 0 execution)  
**Model:** `nvidia/nemotron-3-super-120b-a12b`  
**Pinned tokenizer revision:** `2dc98e2afe4face0e4ce40972a915c45368bd34a`  
**Endpoint:** `https://integrate.api.nvidia.com/v1/chat/completions`  
**Method:** Single-shot completion with `max_tokens=1` (no nested retries; no 429 retry)  
**Scientific mode after qualification:** still `PER_REQUEST_TOKEN_COUNT_MODE = "unavailable"`

---

## Final verdict

# `NIM_LOCAL_TOKENIZER_QUALIFIED`

All **7/7** authorized probes returned `delta = local_prompt_tokens − usage.prompt_tokens == 0` with matching model identity. NVIDIA-specific qualification evidence is `PASSED` / `evidence_validated=true`. DeepInfra/OpenRouter are **not** authorized. Scientific per-request mode was **not** activated.

---

## 1. Pre-probe integrity checks

| Check | Result |
|---|---|
| Tokenizer artifact SHA-256 vs `PINNING_MANIFEST.json` | **OK** |
| Chat-template hash `575fb74f…bb68a` | **OK** |
| Offline load `trust_remote_code=False` | **OK** |
| FROZEN_MANIFEST | **14/14** |
| `config/experiment0_config.py` / Exp1 actor+witness hashes | **Unchanged** |
| Archived run `e0_20261007T132027Z` resume/analysis | **Blocked** |
| Six Stage-A fixture bodies + SHA-256 | **OK** |
| `NIM_API_KEY` present (not printed) | **OK** |
| Default mode `unavailable` | **OK** |

No external calls were made until these checks passed.

---

## 2. Call budget and pacing

| Metric | Value |
|---|---:|
| Authorized max successful probes | 7 |
| Hosted calls attempted | **7** |
| Successful (HTTP 200 + usable `usage.prompt_tokens`) | **7** |
| Rate-limited (429) | **0** |
| Failed / mismatched | **0** |
| Nested retries | **0** (dedicated `post_chat_completions_once`) |
| Inter-probe pacing | ~35 s after each success (bounded; no wait-retry on 429) |

Native `/tokenize` or `/v1/messages/count_tokens` on the hosted integrate API was **not** confirmed for this model in Stage A; qualification used the existing count-via-`max_tokens=1` technique with identical `messages` and `chat_template_kwargs.enable_thinking=false`.

---

## 3. Probe results (signed deltas)

| # | Fixture | Body SHA-256 (prefix) | Local | Provider `prompt_tokens` | Δ | Cached tokens | Request ID |
|---|---|---|---:|---:|---:|---:|---|
| 1 | `minimal_synthetic` | `67cf9d06…` | 27 | 27 | **0** | 0 | `chatcmpl-a2c7313e-…` |
| 2 | `short_actor_t1` | `02467b41…` | 168,008 | 168,008 | **0** | 0 | `chatcmpl-d5ab73e3-…` |
| 3 | `short_witness` | `0dcdc9c5…` | 168,823 | 168,823 | **0** | 0 | `chatcmpl-c53cd350-…` |
| 4 | `multi_message_actor` | `edcc6577…` | 168,244 | 168,244 | **0** | 167,024 | `chatcmpl-1407acd8-…` |
| 5 | `revision_shaped_actor` | `92e05997…` | 168,266 | 168,266 | **0** | 167,024 | `chatcmpl-043e4668-…` |
| 6 | `worst_case_actor` | `7525c890…` | 207,876 | 207,876 | **0** | 167,024 | `chatcmpl-fb114323-…` |
| 7 | `worst_case_witness` | `0f31ec51…` | 170,414 | 170,414 | **0** | 167,024 | `chatcmpl-4028a064-…` |

**Notes**

- `short_actor_t1` / `short_witness` are history-short but **~168k** tokens (system+sources dominate)—not short-context probes.
- `minimal_synthetic` is the only truly small probe (27 tokens).
- Provider `prompt_tokens` was used for capacity equivalence even when `cached_tokens` was large; sequence length matched local counts.
- `model_returned` was always `nvidia/nemotron-3-super-120b-a12b`.
- `finish_reason=length` with `max_tokens=1` is expected for count-only calls.
- Equal prompt counts **do not alone** prove thinking-flag behavioral fidelity; probes used `enable_thinking=false` and observed `reasoning_tokens=0` / no `reasoning_content` on the minimal probe—supporting consistency, not a scientific claim.

Raw per-probe records: `experiment0/qualification_fixtures/nim_probe_results/*.json`

---

## 4. Tokenizer / template identity

| Field | Value |
|---|---|
| HF repo | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` |
| Revision | `2dc98e2afe4face0e4ce40972a915c45368bd34a` |
| Template SHA-256 | `575fb74f54ed264df9047d0ecce3c98938aae953fb4f50356675706264cbb68a` |
| `enable_thinking` | `false` |
| `add_generation_prompt` | `true` |
| System placement | OpenAI prepend (shared `assemble_openai_chat_messages`) |

---

## 5. Evidence validation outcome

File: `experiment0/tokenizers/nemotron3_super_120b_bf16/QUALIFICATION_EVIDENCE.json`

| Field | Value |
|---|---|
| `provider_profile` | `nvidia-nim` |
| `hosted_qualification_status` | **`PASSED`** |
| `evidence_validated` | **`true`** |
| `validator_id` | `stage_b_nim_qualification_20261008` |
| Probe count | **7** (all `delta==0`, `status=PASS`) |
| `TokenizerQualificationEvidence.authorizes(...)` | **True** for `nvidia-nim` |
| Authorizes DeepInfra / OpenRouter | **False** (profile-bound) |
| `PER_REQUEST_TOKEN_COUNT_MODE` | still **`unavailable`** |

With evidence loaded, `LocalNemotronChatTokenCounter` for `nvidia-nim` returns trust **`verified`**. Scientific collection still uses `UnavailableTokenCounter` until a **separate pre-launch approval** switches mode (e.g. to `local_hf`).

---

## 6. Post-qualification regression

| Suite | Result |
|---|---|
| Exp1 | **113** passed |
| Exp0 | **76** passed |
| Combined | **189** passed, 0 failed, 0 skipped |
| Prior combined baseline | 189 (unchanged count) |
| FROZEN_MANIFEST | **14/14** |
| Experiment launched | **No** |
| Archived run resumed | **No** |
| Default scientific gate | **Closed** (`unavailable`) |

---

## 7. Remaining backend uncertainties

1. Qualification is **NVIDIA NIM integrate API only**—not transferable to OpenRouter/DeepInfra without a new Stage B.  
2. Prompt caching changes billing/cache stats but did not change `prompt_tokens` vs local in these probes.  
3. Thinking-flag scientific behavior is not fully proven by token equality alone.  
4. Hosted native tokenize endpoints remain unused/unconfirmed here.  
5. Scientific activation of `local_hf` still requires explicit approval.

---

## 8. Can NVIDIA-local counting be trusted for capacity authorization?

**Yes — for provider profile `nvidia-nim` only**, once scientific mode is deliberately switched to use `LocalNemotronChatTokenCounter` with this evidence record.

**Not yet active** on the scientific path (`unavailable` remains the default).

---

## Strict restrictions (honored)

No Exp0 launch; no schedule; no OpenRouter/DeepInfra; no retry amplification; no protocol/retry-policy edits; no Git; archived run untouched; no scientific outcome inspection.
