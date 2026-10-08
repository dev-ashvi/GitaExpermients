# Experiment 0 Instrumentation Amendment v1.0.1

**Date:** 2026-10-07  
**Status:** Pre-run instrumentation amendment (no Experiment 0 episode data existed)  
**Parent scope:** `docs/experiment0_scope_v1.0.md` (scientific design unchanged)

---

## Change

| Parameter | Previous | Calibrated |
|---|---:|---:|
| `MAX_TOKENS_WITNESS` | 600 | **1600** |
| `MAX_TOKENS_ACTOR` | 800 | 800 (unchanged) |

## Reason

NIM Witness structured-output serialization required additional output budget.

At `MAX_TOKENS_WITNESS=600`, calibration case `overconfident_clear_violation` returned:

- `finish_reason = length`
- `completion_tokens = 600`
- truncated mid-`violations[]` JSON
- parse failure despite semantically correct prefix (`overall_score=0.0`, `verdict=REJECT`)

This was confirmed as **output-budget truncation**, not a scoring-threshold issue.

Controlled sweep of Witness budgets `{600, 800, 1000, 1200, 1600}` with frozen model, prompts, rubric, schema, temperature=0.0, `enable_thinking=False`, and frozen discrimination expectations selected **1600** as the **smallest tested** budget satisfying complete valid JSON, schema validity, no `finish_reason=length`, and correct discrimination on all calibration cases.

## Explicitly unchanged

- Model IDs
- Temperature
- Prompts / Witness rubric / schema
- Scoring and GO/NO-GO thresholds
- Source packet S1–S5
- Conditions C1/C2, N=30+30
- User responses T15–24
- RCVR / FINAL metrics definitions
- Capacity fraction 0.85
- Reasoning mode `enable_thinking=False`
- Experiment 1 (all files / hashes)

## Timing

Calibration and this amendment occurred **before episode 1**. No experimental outcome data existed when the change was made.
