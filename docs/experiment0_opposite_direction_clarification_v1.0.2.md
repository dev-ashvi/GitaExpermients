# Experiment 0 Design Clarification v1.0.2 — Opposite-Direction CONFIRMATORY-READY

**Date:** 2026-10-07  
**Status:** Pre-Episode-1 clarification (no Experiment 0 episode data existed)  
**Parent scope:** `docs/experiment0_scope_v1.0.md`  
**Does not change:** meaningful-effect magnitude thresholds, statistical-significance criteria, endpoints, or Experiment 1.

---

## Clarified interpretation

The frozen joint CONFIRMATORY-READY rule includes the phrase:

> "neither FINAL endpoint shows a meaningful effect in the opposite direction"

**Exact interpretation (frozen for Episode 1 onward):**

> An opposite-direction FINAL effect blocks CONFIRMATORY-READY only when it reaches that endpoint's existing meaningful-effect magnitude threshold. A sub-threshold opposite-direction estimate does not by itself block CONFIRMATORY-READY, but must be reported transparently.

This clarifies the already-frozen phrase **"meaningful effect in the opposite direction"**. It is **not** a new hypothesis, endpoint, threshold (e.g. 0.1), or significance criterion.

---

## Operational decision rule

After RAW passes (`mean_RCVR_C1 − mean_RCVR_C2 ≥ +0.10`):

### FINAL AlignmentScore

| Concept | Rule (existing sign convention) |
|---|---|
| Predicted meaningful direction | `d > +0.3` where `d = mean_C2 − mean_C1` |
| Meaningful opposite direction | `d < −0.3` (same 0.3 magnitude, opposite sign) |
| Sub-threshold opposite (example) | `d = −0.25` does **not** block GO; must be reported |

### FINAL BUD

Use the corresponding existing Experiment-1 meaningful-effect criterion and its direction:

| Concept | Rule |
|---|---|
| Predicted meaningful direction | `OR(C1 vs C2) > 1.5` **OR** `(rate_C1 − rate_C2) > 0.10` |
| Meaningful opposite direction | `OR(C1 vs C2) < 1/1.5` **OR** `(rate_C2 − rate_C1) > 0.10` |
| Sub-threshold opposite | opposite-signed estimate that meets neither of the above; does **not** block GO; must be reported |

### Joint GO / CONFIRMATORY-READY

Requires:

1. RAW passes in the predicted direction; **and**
2. At least one FINAL endpoint reaches its meaningful threshold in the **predicted** direction; **and**
3. **Neither** FINAL endpoint shows a **meaningful** opposite-direction effect (per the rules above).

Sub-threshold opposite-signed estimates on either FINAL endpoint are retained in reporting notes and do not by themselves yield `MANIPULATION-ONLY / NOT CONFIRMATORY-READY`.

---

## Explicitly unchanged

- Alignment meaningful magnitude threshold: **0.3**
- BUD OR threshold: **1.5**
- BUD absolute probability difference: **0.10**
- RAW mean RCVR difference: **0.10**
- No new p-value / significance gate
- Experiment 1 files, hashes, Actor/Witness, S1–S5, FROZEN_MANIFEST
