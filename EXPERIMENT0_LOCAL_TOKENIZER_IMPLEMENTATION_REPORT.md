# Experiment 0 — Local Nemotron Token Counter (Stage A)

**Date:** 2026-10-08  
**Feasibility verdict accepted:** `LOCAL_TOKENIZER_FEASIBLE_PENDING_PROVIDER_VALIDATION`  
**Hosted qualification:** **Not executed** (Stage B deferred)  
**Inference / paid APIs:** **None**

---

## Final verdict

# `LOCAL_COUNTER_IMPLEMENTED_UNVERIFIED`

Offline counter implemented, pinned, tested, and integrated with the existing
`TokenCounter` / capacity-gate path. All scientific authorization remains
**fail-closed** (`UNVERIFIED` / default `unavailable` mode). Stage B hosted
probes are prepared as fixtures only.

---

## 1. Tokenizer revision and artifact hashes

| Field | Value |
|---|---|
| HF repo | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` |
| Pinned revision | `2dc98e2afe4face0e4ce40972a915c45368bd34a` |
| API model id | `nvidia/nemotron-3-super-120b-a12b` |
| Local dir | `experiment0/tokenizers/nemotron3_super_120b_bf16/` |
| `trust_remote_code` | **false** (not required; tokenizer loads offline) |
| Weights downloaded | **None** |

| File | Bytes | SHA-256 |
|---|---:|---|
| `tokenizer.json` | 17,077,484 | `623c34567aebb18582765289fbe23d901c62704d6518d71866e0e58db892b5b7` |
| `tokenizer_config.json` | 177,209 | `10f93eabcb9b1602fbb991d6308e787ce1df28ee9cd7a1c6d1e8c3f338b957bc` |
| `special_tokens_map.json` | 563 | `e9435fefd6d838fd9fcbbc44b97a8e3ff322be7f6dfb7e4fd2468586574bb52b` |
| `chat_template.jinja` | 10,771 | `575fb74f54ed264df9047d0ecce3c98938aae953fb4f50356675706264cbb68a` |

**Chat-template hash used for counting:**  
`575fb74f54ed264df9047d0ecce3c98938aae953fb4f50356675706264cbb68a`  
(equals both on-disk `chat_template.jinja` and `tokenizer.chat_template`)

Manifest: `experiment0/tokenizers/nemotron3_super_120b_bf16/PINNING_MANIFEST.json`

---

## 2. Dependencies installed / used

No new packages were installed for this stage. Environment at acquisition/test:

| Package | Version |
|---|---|
| `transformers` | 4.49.0 |
| `huggingface_hub` | 0.29.1 |

Tokenizer load: `AutoTokenizer.from_pretrained(..., local_files_only=True, trust_remote_code=False)`.

`apply_chat_template(..., tokenize=True, add_generation_prompt=True, enable_thinking=False)` works on this version without remote code.

---

## 3. Files changed / added

| Path | Role |
|---|---|
| `experiment0/tokenizers/nemotron3_super_120b_bf16/*` | Pinned artifacts + `PINNING_MANIFEST.json` + `QUALIFICATION_EVIDENCE.json` (PENDING stub) |
| `experiment0/tokenizers/README.md` | Notes |
| `experiment0/providers/message_assembly.py` | Shared OpenAI message assembly |
| `experiment0/providers/nim_provider.py` | Uses shared assembly (regression-tested) |
| `experiment0/local_nemotron_counter.py` | `LocalNemotronChatTokenCounter` |
| `experiment0/tokenizer_qualification.py` | Evidence schema + authorize rules |
| `experiment0/engineering_config.py` | Documents `local_hf` mode (default still `unavailable`) |
| `experiment0/run_experiment.py` | Optional `local_hf` wiring (still UNVERIFIED → fail closed) |
| `experiment0/qualification_fixtures/*` | Offline Stage-B probe fixtures + builder |
| `experiment0/tests/test_exp0_message_assembly.py` | Assembly equivalence |
| `experiment0/tests/test_exp0_local_nemotron_counter.py` | Offline counter tests |
| `EXPERIMENT0_LOCAL_TOKENIZER_IMPLEMENTATION_REPORT.md` | This report |

**Unchanged (scientific):** `config/experiment0_config.py`, Exp1 sources, prompts, metrics, retries, archived run ledgers.

---

## 4. Message serialization mapping

```
CapacityGatingAnthropicClient receives Anthropic (system, messages)
  → LocalNemotronChatTokenCounter.assemble_messages
      == assemble_openai_chat_messages  (same as NimChatProvider._build_payload)
  → tokenizer.apply_chat_template(
        openai_messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
     )
  → len(token_ids)
```

System placement: non-empty `system` prepended as first OpenAI `{role: system}` message.  
Generation prompt: assistant start with empty thinking close (`<think></think>` when thinking disabled).

---

## 5. Test results

| Suite | Result |
|---|---|
| Exp1 | **113** passed |
| Exp0 | **76** passed |
| Combined | **189** passed, 0 failed, 0 skipped |
| Prior combined baseline | 168 |
| New tests this stage | +21 |
| FROZEN_MANIFEST | **14/14** |
| Scientific config/actor/witness hashes | **Unchanged** |
| Archived run resume/analysis | **Still blocked** |

---

## 6. Counter verification state

| Item | State |
|---|---|
| Default scientific mode | `PER_REQUEST_TOKEN_COUNT_MODE = "unavailable"` |
| Local counts returned trust | **`UNVERIFIED`** |
| `is_provider_verified` | **False** (no PASSED evidence) |
| Evidence file | `QUALIFICATION_EVIDENCE.json` with `hosted_qualification_status=PENDING_STAGE_B`, `evidence_validated=false` |
| Can a boolean alone promote VERIFIED? | **No** — requires validated evidence with matching hashes, `PASSED`, non-empty probes all `delta==0` |
| Capacity gate on local counts today | **Fail closed** (`Trustworthy token count unavailable`) |

---

## 7. Offline counts for qualification fixtures

From `experiment0/qualification_fixtures/INDEX.json` (local UNVERIFIED):

| Fixture | Local prompt tokens | Output budget |
|---|---:|---:|
| `short_actor_t1` | 168,008 | 800 |
| `short_witness` | 168,823 | 1,600 |
| `multi_message_actor` | 168,244 | 800 |
| `revision_shaped_actor` | 168,266 | 800 |
| `worst_case_actor` | **207,876** | 800 |
| `worst_case_witness` | **170,414** | 1,600 |

**Note:** Worst-case local counts **numerically match** the previously reported NVIDIA `usage.prompt_tokens` priors (207,876 / 170,414). This is **encouraging** but **does not** constitute Stage B qualification (must re-probe live provider with the exact fixture bodies).

Each fixture JSON stores the full `provider_facing_request_body` + SHA-256 for exact Stage B comparison.

---

## 8. Remaining provider-specific uncertainties

1. Hosted NIM may still differ from Transformers template application on edge cases.  
2. OpenRouter/DeepInfra template / usage provenance untested.  
3. `transformers` 4.49.0 vs docs mentioning 5.3.0 for **model** load — tokenizer path works; pin/revisit if upgrading.  
4. Cached-token billing fields must not be confused with sequence length at Stage B.  
5. Scientific path still blocked until evidence authorizes VERIFIED **and** mode intentionally switched.

---

## 9. Exact hosted probes recommended for Stage B

For each fixture in `experiment0/qualification_fixtures/*.json` (six total):

1. POST the stored `provider_facing_request_body` to the target provider (`nvidia-nim` first).  
2. Prefer native count endpoint if confirmed available; else `max_tokens=1` completion (same as current preflight).  
3. Read `usage.prompt_tokens`.  
4. Require **Δ = local_prompt_tokens − usage.prompt_tokens == 0**.  
5. On all six PASS: set `QUALIFICATION_EVIDENCE.json` with `hosted_qualification_status=PASSED`, `evidence_validated=true`, `validator_id`, `validated_utc`, and `probe_results[]`.  
6. Only then may `LocalNemotronChatTokenCounter` return `VERIFIED` for that profile.

Do **not** mark VERIFIED because a markdown report exists.

---

## 10. Blockers

| Type | Status |
|---|---|
| Scientific protocol | None changed |
| Operational (clean N=60) | Still blocked: per-request mode unavailable / local UNVERIFIED fail-closed until Stage B |
| Implementation | **None** for Stage A |
| Archived run | Remains excluded |

---

## Strict restrictions (honored)

No NVIDIA/OpenRouter/DeepInfra inference calls; no weight downloads; no scientific run/schedule/resume/analysis; no protocol or retry changes; no Git commit.

**STOP.** Await explicit approval for Stage B hosted qualification.
