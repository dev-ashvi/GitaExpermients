# Experiment 0 — Tokenization Feasibility Audit

**Date:** 2026-10-08  
**Mode:** Read-only technical assessment (no implementation, no downloads, no API calls)  
**Prior status:** `P0_ENGINEERING_GATES_PARTIALLY_CLOSED`  
**Archived run (excluded):** `e0_20261007T132027Z` / `ABORTED_OPERATIONAL_RATE_LIMIT_PRE_ANALYSIS`

---

## Final verdict

# `LOCAL_TOKENIZER_FEASIBLE_PENDING_PROVIDER_VALIDATION`

Local exact counting is **practically feasible** using the official Hugging Face tokenizer + `apply_chat_template(..., enable_thinking=False)`, wired into the existing `TokenCounter` / `CapacityGatingAnthropicClient` interfaces — **without** 120B weights. It is **not yet scientifically defensible as `VERIFIED`** until hosted qualification probes show that local counts match the **target provider’s** `usage.prompt_tokens` on the same serialized payloads (especially if migrating off NVIDIA NIM to OpenRouter/DeepInfra).

Evidence is insufficient to claim a proven provider-independent upper bound, or that preflight-only is equivalent to per-request exact counting on a 262k window.

---

## 1. Actual request serialization trace

### 1.1 Call chain (scientific Exp0 path)

```
Experiment0EpisodeRunner._run_turn
  → Actor.generate / Actor.generate_revision
      → Actor._send → Actor._call_api
          → client.messages.create(model, max_tokens, temperature, system, messages)
  → Witness.evaluate
      → Witness._call_api
          → client.messages.create(...)
```

Client stack as constructed in `run_experiment.build_capacity_clients` / `run_one_episode`:

```
CapacityGatingAnthropicClient          # capacity check HERE
  → NimAnthropicCompatClient           # Anthropic → ProviderRequest
      → NimChatProvider.complete       # OpenAI-shaped JSON POST
          → integrate.api.nvidia.com/v1/chat/completions
```

### 1.2 Representations at each stage

| Stage | Representation | What changes |
|---|---|---|
| **Actor / Witness** | Anthropic-shaped: separate `system: str` + `messages: [{role, content}]` (plain strings; no content blocks) | History assembly; revision inserts temporary assistant + Buddhi user message; Witness builds single user message with SOURCE PACKET / USER TURN / AGENT OUTPUT |
| **CapacityGatingAnthropicClient** | Same Anthropic-shaped `(system, messages)` + role `max_tokens` | **Does not mutate prompts.** Passes `(system, messages)` to `TokenCounter.count_prompt_tokens`. Default counter is `UnavailableTokenCounter` → fail closed |
| **NimAnthropicCompatClient** | Builds `ProviderRequest(system, messages, max_tokens, temperature, enable_thinking)` | Copies messages; sets `enable_thinking` from constructor (`e0.ENABLE_THINKING=False`) |
| **NimChatProvider._build_payload** | OpenAI chat messages: **prepends** `{role: system, content: system}` then user/assistant turns; adds `chat_template_kwargs: {enable_thinking: false}`; omits `top_p` / `seed` | System placement changes (Anthropic-separate → first OpenAI message). This is the last client-side serialization |
| **Hosted inference** | Server applies **chat template** (special tokens, role markers, generation prompt, thinking markers) then tokenizes | Client never sees templated string; billed/capacity-relevant count is post-template |

### 1.3 Role-specific message shapes (confirmed from code)

**Actor RAW (`generate`):**  
`history` + `[{role: user, content: turn_prompt}]`

**Actor revision (`generate_revision`):**  
`history` + user prompt + assistant candidate + user Buddhi feedback (temporary; not committed)

**Actor commit:** user prompt + assistant final + frozen user response (3-part)

**Witness:** system = protocol + output JSON instructions; messages = one user message embedding source packet + turn + agent output. No multi-turn Witness history.

**Tools:** none in Exp0 path.

### 1.4 What the capacity gate currently “counts”

| Mode | What is counted | Trust |
|---|---|---|
| Default `PER_REQUEST_TOKEN_COUNT_MODE=unavailable` | Nothing (`None`) | `UNAVAILABLE` → fail closed |
| Test `VerifiedFixedTokenCounter` | Injected integer (not real tokenization) | `VERIFIED` (test-only) |
| `LiveProviderTokenCounter` / preflight `count_prompt_tokens` | Provider `usage.prompt_tokens` after a `max_tokens=1` chat completion on the **OpenAI-shaped** payload with `enable_thinking` | Treated as `VERIFIED` for that provider |

**Critical discrepancy:** The gate’s `TokenCounter` API receives **Anthropic-shaped** `(system, messages)`. Provider truth is **OpenAI-shaped messages + server chat template**. Any local counter must:

1. Apply the **same** system-prepending transform as `NimChatProvider._build_payload`, and  
2. Run `apply_chat_template(..., add_generation_prompt=True, enable_thinking=False)`, and  
3. Count the resulting token IDs  

Counting raw concatenated text, or Anthropic fields without template expansion, is **not** provider-exact.

Preflight already builds `ProviderRequest` and uses provider counts — that path is closer to truth than the gate’s Anthropic-shaped interface unless the local counter mirrors `_build_payload`.

---

## 2. Model / tokenizer identification

### 2.1 Confirmed (from repo + official docs inspected during audit)

| Item | Value |
|---|---|
| Exp0 API model id | `nvidia/nemotron-3-super-120b-a12b` (`config/experiment0_config.py`) |
| Official HF weight/tokenizer card | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` |
| Related quantized card | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8` (includes `chat_template.jinja`) |
| Documented context (model card) | Up to **1M** tokens; HF default config often **256k** due to VRAM |
| Reasoning control | `enable_thinking` via chat template / `chat_template_kwargs` (Exp0 freezes `False`) |
| NIM client behavior | Sends `chat_template_kwargs.enable_thinking=False` (unit-tested) |
| Local tokenizer load (docs) | `AutoTokenizer.from_pretrained("nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16")` |
| Transformers | Integrated since **v5.3.0**; older versions need `trust_remote_code=True` for **model** load (tokenizer-only path still to be pinned at implement time) |
| Weights required for counting? | **No** — tokenizer + template files suffice for offline ID counts |

### 2.2 Unresolved (must verify before marking VERIFIED)

| Assumption | Why unresolved |
|---|---|
| Hosted NIM `usage.prompt_tokens` ≡ HF `apply_chat_template` length with identical kwargs | Serving stack (vLLM/TensorRT-LLM/NIM) may differ slightly from Transformers template application |
| Cloud `integrate.api.nvidia.com` exposes `/tokenize` or `/v1/messages/count_tokens` for this model | Self-hosted NIM docs list these endpoints; **hosted API availability for this exact model is not confirmed in-repo** |
| OpenRouter/DeepInfra apply the same template and report backend-true `prompt_tokens` | Router may transform messages; usage may be estimated; fallback providers may differ |
| BF16 vs FP8 tokenizer/template byte-identical | Likely shared, not proven in this audit |
| Quantization / engine changes prompt token IDs | Hypothesis: usually unchanged; must probe |
| Exact tokenizer file set + hashes to pin | Not downloaded (audit restriction); pin at implement/qualify time |

### 2.3 Suggested verification from official sources (no downloads performed)

1. HF file list for BF16: `tokenizer.json` / `tokenizer_config.json` / `special_tokens_map.json` / `chat_template.jinja` (or embedded template) — record SHAs.  
2. NVIDIA NIM reasoning docs: confirm `chat_template_kwargs.enable_thinking` is honored for **Nemotron 3 Super** on the hosted endpoint used by Exp0.  
3. OpenRouter model page + provider routing docs: context window per backend; pin DeepInfra; disable fallbacks.  
4. DeepInfra model page: advertised context (public pages cite **262,144** — treat as **advertised**, not yet Exp0-verified).  
5. Whether OpenRouter/DeepInfra expose a pre-inference count API for this model (unknown; assume **no** until shown).

---

## 3. Confirmed facts vs unresolved assumptions

### Confirmed

- Per-request gate exists and fails closed without a trustworthy counter.  
- Preflight uses live NIM `usage.prompt_tokens` on worst-case Actor/Witness `ProviderRequest`s against profile `nvidia-nim` @ 1M × 0.85.  
- NVIDIA prior worst-case ≈ Actor **207,876** + 800; Witness **170,414** + 1,600.  
- Correct 262k arithmetic: budget **222,822**; both provisionally fit with **~14,146** Actor headroom — **NVIDIA counts only**.  
- Nested retries can amplify to **9** HTTP attempts per logical Actor call (frozen 3×3).  
- Exp0 does not use tools; messages are plain strings.  
- Official HF tokenizer + `enable_thinking` chat-template control exists for this model family.  
- `estimate_tokens` in Exp1 (`~3 chars/token`) is an **overestimate heuristic**, not a VERIFIED counter.

### Unresolved

- Exact local↔NIM count equality.  
- Exact local↔DeepInfra/OpenRouter count equality.  
- Whether 262,144 is the **enforced** backend limit under a pinned DeepInfra route.  
- Hosted availability of native tokenize/count_tokens without a completion.  
- Magnitude of template/router mismatch relative to ~14k headroom.

---

## 4. Option comparison

### Option A — Hugging Face tokenizer locally

| Dimension | Assessment |
|---|---|
| Accuracy potential | High **if** template + `enable_thinking=False` + system-prepending match serving |
| Dependencies | `transformers` (pin ≥5.3.0 recommended), tokenizer files only (~tens of MB, not 120B) |
| Cost / rate-limit | Near-zero per request after one-time load |
| Compatibility | Must be **provider-bound** and re-qualified per backend |
| Scientific risk | Low if fail-closed on load/version mismatch; high if marked VERIFIED without probes |

**Recommendation:** Primary path.

### Option B — Provider-native tokenizer endpoint

| Provider | Evidence |
|---|---|
| Self-hosted NIM | Docs: `POST /tokenize`, `POST /v1/messages/count_tokens` (count without generation) |
| Hosted NVIDIA API used by Exp0 | **Not confirmed** for this model; today Exp0 uses **completion with `max_tokens=1`** |
| OpenRouter / DeepInfra | **No** in-repo evidence of a reliable pre-inference count API |

Even a true count endpoint still adds **one network call per scientific request** (~3k extra calls projected for N=60) — rate-limit/cost regress versus aborted NIM run.

**Recommendation:** Secondary / qualification aid only; not default scientific path.

### Option C — Provider-reported usage calibration

Use controlled hosted probes: send identical payloads; compare `usage.prompt_tokens` to local `apply_chat_template` length.

| Establishes | Does not establish |
|---|---|
| Equivalence for probed shapes on that provider | Authorization of the **same** request from its own post-response usage |
| Confidence to set `VERIFIED` for a pinned counter+profile | Transferability to another backend without re-probe |

**Recommendation:** Mandatory gate to promote Option A from “loaded” to **VERIFIED**.

### Option D — Conservative offline upper bound

A **proven** bound requires a theorem relating character/byte length to token length for this tokenizer (e.g. worst-case tokens ≤ f(bytes)). No such proven, provider-independent bound exists in-repo. Char÷k heuristics (including Exp1 `estimate_tokens`) are **not** eligible for `TokenCountTrust.VERIFIED`.

**Recommendation:** Reject as VERIFIED authorizer. May only appear as diagnostic `UNVERIFIED` telemetry.

### Option E — Existing preflight only

Actor worst-case preflight fills 24 turns with max-length assistant blobs + worst user responses + T25 prompt — intended to dominate growing history. Witness worst-case uses max-filled actor output in one eval message. Revision temporary context is unlikely to exceed the T25-filled envelope under current frozen budgets, but:

- Preflight is **provider-specific** and stale if backend/template changes.  
- Does not re-check each request (P0 requirement).  
- On **262k** with ~14k headroom, any under-estimate of template overhead is dangerous.  
- Does not satisfy “exact serialized request” per call.

**Recommendation:** Keep as **start-of-run** safety net; **not** a substitute for per-request VERIFIED counting on smaller windows.

---

## 5. Backend compatibility concerns

### NVIDIA NIM (current)

- Context claim used in engineering profile: **1M verified for NIM hosting profile only**.  
- Counting today: live `usage.prompt_tokens` via `max_tokens=1`.  
- `enable_thinking=False` already in payload.  
- Offline tokenizer must reproduce NIM usage under that flag.  
- Cached tokens appear in diagnostics (`prompt_tokens_details.cached_tokens`) — caching must **not** reduce counted prompt size for capacity (capacity cares about sequence length, not billable unique tokens). Use `usage.prompt_tokens`, not “new” tokens only.

### OpenRouter → pinned DeepInfra (not approved yet)

| Concern | Implication |
|---|---|
| Advertised context **262,144** on OpenRouter/DeepInfra pages | Candidate only until Exp0 profile sets `context_limit_verified=True` after evidence |
| Multiple OpenRouter providers (DeepInfra, DekaLLM, …) | **Must pin** DeepInfra and **disable fallback** or counts/limits may silently change |
| Router message transforms | May insert/alter system content → token delta |
| Usage provenance | Must confirm `prompt_tokens` is backend tokenizer, not router estimate |
| `chat_template_kwargs` | May be stripped or ignored — must probe thinking-off behavior |
| Model id string | OpenRouter: `nvidia/nemotron-3-super-120b-a12b`; DeepInfra may use HF-style id — pin exactly |

Do **not** reuse NVIDIA 207k/170k counts for DeepInfra authorization.

---

## 6. Context headroom assessment

\[
0.85 \times 262\,144 = 222\,822.4
\]

Using **NVIDIA** priors:

| Role | LHS | Headroom vs 222,822 |
|---|---:|---:|
| Actor | 208,676 | **~14,146** (~6.4% of budget) |
| Witness | 172,014 | **~50,808** |

### How mismatch could consume Actor headroom

| Risk | Order-of-magnitude note |
|---|---|
| Extra role / special tokens per message | Actor late turns: O(70) messages; tens of tokens each → O(10³) possible |
| `enable_thinking` accidentally True | Generation prompt opens thinking block; prompt-side delta may be small, but behavior/science breaks — treat as hard fail |
| Provider-inserted instructions | Unknown; can be large |
| Template version skew | 1% of ~208k ≈ **2k** tokens; 5% ≈ **10k** — can erase most headroom |
| Revision / re-eval | Extra messages; usually inside worst-case envelope if preflight is honest |
| Long Unicode / source packet | Tokenizer-dependent; must probe with real S1–S5 text |

**Evidence bar to approve a 262k backend under 85% rule:**

1. Remeasure Actor/Witness **worst-case** `usage.prompt_tokens` on that backend.  
2. Local counter matches those probes (prefer **absolute difference 0** on qualification set; see §9).  
3. Documented/observed hard context limit ≥ 262,144 with pin + no fallback.  
4. `enable_thinking=False` confirmed in returned behavior/metadata.  
5. LHS + reserved_out ≤ 222,822 with margin policy (recommend retaining full 15% rule without “borrowing” headroom for unmeasured risk).

If local counts run **systematically below** provider counts, **reject** the local counter for that provider (unsafe under-authorization).

---

## 7. Scientific isolation implications

| Topic | Assessment |
|---|---|
| Shared tokenizer process | **Safe** if stateless library; not shared conversation state |
| Actor vs Witness clients | Keep **separate** gating clients (already done); never feed Witness payloads into Actor history |
| Telemetry | Log counts, role, turn, template/tokenizer hashes — **not** Witness scores/reasoning into Actor-visible artifacts |
| Determinism | Pin tokenizer revision + template hash; fail closed on mismatch |
| Introduced risk | Accidental logging of full Witness user content in capacity debug; mitigate with redaction / size-only logs |

Offline counting does **not** inherently break Actor/Witness isolation.

---

## 8. Recommended minimal design (do not implement yet)

Prefer extending existing interfaces; no new tokenization microservice.

1. **`LocalNemotronChatTokenCounter(TokenCounter)`**  
   - Input: Anthropic `(system, messages)` from `CapacityGatingAnthropicClient`  
   - Transform: identical to `NimChatProvider._build_payload` message list  
   - Count: `tokenizer.apply_chat_template(..., tokenize=True, add_generation_prompt=True, enable_thinking=False)` → `len(ids)`  
   - Return `(n, VERIFIED)` only if profile binding + qualification flag set; else `UNVERIFIED` / fail closed  

2. **Injection point:** `build_capacity_clients(..., token_counter=...)` / engineering mode `injected` or new `local_hf` mode in `engineering_config.py` only.

3. **Provider binding:** Counter carries `provider_profile` + expected API model id; refuse to authorize if active profile ≠ bound profile.

4. **Pinning:** Vendored or cached tokenizer dir with recorded file SHAs + `chat_template` hash + `transformers` version in run manifest (engineering fields).

5. **VERIFIED status:** Set only after qualification report artifact exists for that provider profile (hashes of probes + max |Δ|).

6. **Mismatch / load errors:** Raise `CapacityGateError` / configuration error — **stop episode**; never truncate.

7. **Multi-provider:** One class, **multiple bound instances** (or subclasses); do not share one VERIFIED flag across NIM and DeepInfra.

8. **Init:** Process-level singleton per pinned path (lazy load once).

9. **Ops evidence:** `last_capacity_check` already on gating client; extend with `tokenizer_id`, `template_hash`, `count_source=local_hf` — no scientific text.

---

## 9. Offline validation plan

### Deterministic unit tests (no network)

- Actor system prompt alone; Witness system prompt alone  
- T1 (empty history) and T25-shaped history (synthetic fills, non-scientific)  
- RAW vs revision message lists  
- Witness re-eval payload shape  
- Real source-packet Unicode (read-only from frozen S1–S5)  
- Exact template string golden hash (fixture)  
- Empty messages; large history  
- Gate: exact threshold pass; +1 fail  
- Missing tokenizer files → fail closed  
- Unknown provider profile → fail closed  
- Version/hash mismatch → fail closed  
- Counter claiming VERIFIED without qualification flag → reject  

### Minimum hosted qualification probes (future; **not** run in this audit)

| Probe | Purpose |
|---|---:|
| Short Actor (T1-like) | Baseline equality |
| Short Witness | Baseline equality |
| Mid-history Actor (~turn 8–12 synthetic) | Multi-message template |
| Full worst-case Actor preflight payload | Capacity-critical |
| Full worst-case Witness preflight payload | Capacity-critical |
| One revision-shaped Actor request | Temporary messages |
| `enable_thinking=True` vs `False` contrast (non-scientific) | Confirm flag affects template as expected |

**Compare:** local count vs `usage.prompt_tokens` on identical OpenAI-shaped body.

**Tolerance:** For capacity authorization, scientifically defensible default is **Δ = 0** on all qualification probes. Any systematic local **under**-count → **reject**. Over-count by a few tokens is safer but still indicates mismatch — investigate; do not paper over with a fudge factor without a new engineering amendment.

**Reject approach when:** Δ ≠ 0 on worst-case probes; template flag ignored; usage missing; provider switches mid-qualification; context limit unverified.

Probe count rationale: ≤ **10** completions with `max_tokens=1` (or native count if available) is enough to cover shapes without doubling the scientific run.

---

## 10. Economic comparison (qualitative; no unsupported precision)

| Approach | Marginal cost | Rate-limit pressure | Reproducibility | Safety |
|---|---|---|---|---|
| **A. Local HF + few probes** | One-time tokenizer fetch + ~O(10) probe calls | Low ongoing | High if pinned | High after qualification |
| **B. Native/pre-inference count every call** | ~1× extra call per inference (~3k/N=60) | **High** (bad given 429 abort) | Provider-dependent | Exact but operationally costly |
| **C. NIM preflight + heuristic offline rule** | Cheap | Low | Weak across providers | **Unsafe** as VERIFIED on 262k |
| **D. Remain fail-closed** | Zero | Zero | N/A | Safe but blocks clean N=60 |

**Priority:** A after qualification ≫ D (temporary) ≫ B ≫ C-as-VERIFIED.

---

## 11. Estimated implementation effort

| Work | Effort (order) |
|---|---|
| Tokenizer pin + `LocalNemotronChatTokenCounter` + wire `engineering_config` | 0.5–1 day |
| Offline tests listed above | 0.5–1 day |
| Hosted qualification harness + report artifact | 0.5 day + probe runtime/cost |
| DeepInfra/OpenRouter profile re-qualification (if migration approved) | Separate session; do not fold into NIM qualification |

**Does not include:** OpenRouter migration, retry-policy amendment, new N=60 schedule, or scientific launch.

---

## 12. Risks and stop conditions

| Risk | Stop / response |
|---|---|
| Local under-counts vs provider | Do not mark VERIFIED; keep fail-closed |
| Thinking flag ignored on target backend | Stop migration/qualification |
| Context limit < advertised | Fail closed; do not run |
| Fallback provider engaged | Stop; require pin |
| Tokenizer download alters scientific prompts | N/A if counter is pure engineering — still ban prompt edits |
| Using aborted run for science | Forbidden (archival guards) |
| Treating NVIDIA counts as DeepInfra | Forbidden |

---

## 13. Recommended next Cursor task

**Title:** Implement and qualify `LocalNemotronChatTokenCounter` for NVIDIA NIM (tokenizer files only; no 120B weights)

**Scope:**

1. Download/pin **tokenizer + template only** for `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` (explicit approval for download).  
2. Implement counter mirroring `NimChatProvider` message assembly + `enable_thinking=False`.  
3. Wire engineering mode; keep scientific protocol untouched.  
4. Offline tests.  
5. Run **minimal hosted qualification probes** against NIM; write `EXPERIMENT0_TOKENIZER_QUALIFICATION_NIM.md`.  
6. Only if Δ=0 (or approved amendment): set per-request mode to local VERIFIED for `nvidia-nim`.  

**Out of scope until separate approval:** OpenRouter/DeepInfra migration; changing frozen retries; creating clean N=60 schedule; resuming archived run.

---

## 14. Execution restrictions (honored)

- Read-only except this audit file  
- No protocol / Exp1 / frozen artifact changes  
- No API calls, paid inference, downloads, Ollama, weights, Git, new schedule  
- No scientific outcome inspection; archived run untouched  
- No token-counter implementation in this task  

---

## Summary table

| Question | Answer |
|---|---|
| Can we count offline exactly in principle? | **Yes**, via official HF tokenizer + chat template |
| Can we mark it VERIFIED today? | **No** — pending provider probes |
| Should we enable live per-request counts? | **No** as default (429 risk) |
| Is preflight-only enough for 262k? | **No** for P0 per-request requirement / thin headroom |
| Is a proven universal bound available? | **No** |
| Verdict | **`LOCAL_TOKENIZER_FEASIBLE_PENDING_PROVIDER_VALIDATION`** |

**STOP.** Await approval before implementing or downloading tokenizer files.
