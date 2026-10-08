# Experiment 0 operational cost/runtime audit

**Run:** `e0_20261007T132027Z`  
**Generated:** `2026-10-07T19:46:08.313344Z`  

Operational only. **No scientific analysis.** Run not resumed.

## Integrity

- No scientific outcome metric computed
- No C1/C2 comparison performed
- No response text inspected/reported
- Run not resumed
- No frozen scientific artifact modified
- Original ledgers not rewritten

## A. Completed-run totals (indices 0–18)

- Completed episodes: **19**
- Total model calls (structural): **984**
- Actor calls (incl. revisions): **492**
- Actor initial calls: **475**
- Actor revision calls: **17**
- Witness calls total: **492**
- Witness RAW calls: **475**
- Witness re-eval calls: **17**
- Recorded input tokens (actor + last-call): **164,158,233**
- Recorded output tokens (actor + last-call): **347,567**
- Recorded total tokens: **164,505,800**
- Recorded latency sum (actor + last-call) ms: **4,835,766**
- Regen turns (token undercount pairs): **17**
- Imputed missing input tokens (approx): **5,875,137**
- Estimated full input (recorded+imputed): **170,033,370**
- Estimated full output (recorded+imputed): **360,006**

## B. Per-episode operational distribution

- Calls/episode: mean=51.79, median=52.0, min=50, max=54
- Input tokens/episode: mean=8,639,907, median=8,645,917, min=8,553,546, max=8,688,211
- Output tokens/episode: mean=18,293, median=18,808, min=11,043, max=21,090

## C. Actor vs Witness usage

### Actor
- Calls: **492** (mean/episode 25.89)
- Recorded input tokens: **83,657,043**
- Recorded output tokens: **312,601**

### Witness (last-call proxy for tokens)
- Calls: **492** (RAW 475, re-eval 17)
- Recorded last-call input tokens: **80,501,190**
- Recorded last-call output tokens: **34,966**

### Revision-related (operational count only)
- Actor revision calls: **17**
- Witness re-eval calls: **17**

## D. Fresh N=60 projection (operational)

- `projected_calls_60` = **3107.4**
- `projected_input_tokens_60` = **518,394,420**
- `projected_output_tokens_60` = **1,097,580**
- +20% allowance input/output: **622,073,304** / **1,317,096**
- Max-envelope (obs max × 60) input/output: **521,292,660** / **1,265,400**

_Operational projections only — not scientific estimates._

## E. Paid-serving cost scenarios

Formula: `cost = input_tokens_millions * input_price_per_million + output_tokens_millions * output_price_per_million`

### Scenario 1 — OpenRouter same-model

- Model: `nvidia/nemotron-3-super-120b-a12b`
- Pricing verification: **VERIFIED_FROM_OPENROUTER_MODELS_API**
- Source: https://openrouter.ai/api/v1/models
- Input/output $/M: **0.08** / **0.45**
- Mean N=60 cost: **$41.97**
- +20% allowance: **$50.36**
- Max envelope: **$42.27**

### Scenario 2 — generic sensitivity

| Price (in/out per M) | Mean N=60 | +20% | Max envelope |
|---|---:|---:|---:|
| $0.05/M in + $0.25/M out | $26.19 | $31.43 | $26.38 |
| $0.08/M in + $0.45/M out | $41.97 | $50.36 | $42.27 |
| $0.10/M in + $0.50/M out | $52.39 | $62.87 | $52.76 |
| $0.30/M in + $0.65/M out | $156.23 | $187.48 | $157.21 |

## F. Free-NIM runtime estimate (no policy recommendation)

### Pacing-only lower bound

Formula: `(projected_calls_60 - 1) * spacing_sec`

- 30s: **25.89 h** (93191 s)
- 60s: **51.77 h** (186382 s)
- 90s: **77.66 h** (279573 s)

### Approximate wall-clock (illustrative)

- Mean recorded inference latency/episode: **254.5 s**
- ~60-episode inference-only: **4.24 h**

- wall_plus_30s_start_spacing_hours: **30.13 h**
- wall_plus_60s_start_spacing_hours: **56.01 h**
- wall_plus_90s_start_spacing_hours: **81.90 h**

_Pacing-only is a lower bound ignoring compute time and retries. Wall+spacing adds recorded per-episode latency sums to spacing; still approximate. No pacing policy recommended here._

## G. Aborted-run sunk operational usage

### Completed episodes 0–18
- Calls: **984**
- Recorded input/output tokens: **164,158,233** / **347,567**

### Incomplete episode-19 attempts (wasted operational)
- Structural calls: **34**
- Recorded input/output (actor+last-call): **5,762,192** / **11,554**

_Isolated NIM pacing diagnostics under diagnostics/runs/nim_rl_* are NOT included in Experiment 0 episode totals._
