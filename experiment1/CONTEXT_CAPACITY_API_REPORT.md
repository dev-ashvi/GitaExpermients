# CONTEXT_CAPACITY_API_REPORT

Measurement-only report. **No frozen files or capacity constants were modified.**  
**No** `messages.create` / generation calls. **No** pilot.

## Status

| item | result |
|---|---|
| Documented context limit for `claude-sonnet-4-6` | **1,000,000 tokens** (verified from Anthropic docs) |
| Anthropic `messages.count_tokens` on exact payloads | **NOT RUN** — `ANTHROPIC_API_KEY` not available in this shell |
| Frozen `MODEL_CONTEXT_LIMIT` / `CONTEXT_CAPACITY_FRACTION` | **unchanged** (still 200000 / 0.90) |

## Documented context limit (`claude-sonnet-4-6`)

Authoritative Anthropic documentation for this exact API model id:

| source | statement |
|---|---|
| [Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows) | Claude Sonnet 4.6 has a **1M-token** context window (default; no beta header required) |
| [Sonnet 4.6 model page](https://platform.claude.com/docs/en/models/sonnet-4-6/overview) | Model ID `claude-sonnet-4-6`; **Context window: 1M tokens**; Max output: 128K |
| [Models overview (legacy table)](https://platform.claude.com/docs/en/about-claude/models/overview) | Claude Sonnet 4.6 → context window **1M tokens** |

Also noted in context-awareness docs: injected token budget for Sonnet 4.6 is **1M** (vs 200k for Sonnet 4.5).

**Mismatch with frozen harness constant (observation only):**  
`config.experiment_config.MODEL_CONTEXT_LIMIT = 200000` understates the documented endpoint capacity by 5×. This report does **not** change that constant.

## Exact payloads prepared for counting (not yet counted)

Script ready at `experiment1/_capacity_api_measure.py`. It builds:

1. **Actor Turn 1** — `build_actor_system_prompt(constitution, build_source_packet())` + frozen turn-1 user prompt  
2. **Witness eval (worst-case actor output size)** — Witness system + `build_eval_user_message` with real source packet + `MAX_TOKENS_ACTOR`-budget synthetic agent output  
3. **Actor Turn 25 projected** — real system + committed history turns 1–24 (frozen prompts/responses; assistant bodies sized to `MAX_TOKENS_ACTOR`) + turn-25 prompt  
4. **Actor Turn 15 revision projected** — history through 14 + candidate + feedback-sized feedback  
5. **Models API** `client.models.retrieve("claude-sonnet-4-6")` for `max_input_tokens` when authenticated  

Method: `client.messages.count_tokens(model="claude-sonnet-4-6", ...)` only.

## Blocker

```text
Could not resolve authentication method. Expected either api_key or auth_token to be set.
```

## How to complete

In this environment, set the key then re-run (or ask the agent to re-run):

```powershell
$env:ANTHROPIC_API_KEY = "<your key>"
cd c:\Users\SERVER\GitaExpermients\experiment1
python _capacity_api_measure.py
```

That writes the completed tables into this file and `_capacity_api_counts.json`.

## Capacity verdicts

| check | result |
|---|---|
| Documented endpoint limit | **1M tokens** |
| API token counts vs 1M / vs frozen 180k | **pending API key** |

No readiness gate was changed by this report.
