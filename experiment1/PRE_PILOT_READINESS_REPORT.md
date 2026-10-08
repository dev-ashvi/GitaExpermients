# PRE_PILOT_READINESS_REPORT

## Verdict

```text
ISSUE-003: resolved
ISSUE-004: resolved
ISSUE-006: resolved

Actor isolation: PASS
Frozen T15-T24 stimuli: PASS
Source identities: PASS
Source extraction QC: PASS
Placeholder scan: PASS
Hash validation: PASS
Context capacity: FAIL
Test suite: PASS

Pilot ready: NO
```

**Reason:** Real five-source packet installed and frozen, but projected context exceeds the frozen 90% capacity limit. No truncation/summarization/limit changes applied. No pilot run performed.

## Context capacity (blocking)

Preflight with actual full TXT packet (`estimate_tokens`, conservative):

| quantity | value |
|---|---:|
| `MODEL_CONTEXT_LIMIT` | 200000 |
| `CONTEXT_CAPACITY_FRACTION` | 0.90 |
| limit (90%) | **180000** |
| source packet characters | 549956 |
| source packet token estimate | ≈183319 |
| actor system prompt tokens | ≈187265 |
| witness system prompt tokens | ≈5081 |
| **actor_estimate** | **231765** |
| **witness_estimate** | **189700** |

Both actor and witness estimates exceed 180000. Per implementation contract: stop and escalate to research owner — do not modify experiment parameters to force a fit.

## Preflight checklist (non-API)

| check | result |
|---|---|
| Actor isolation | PASS |
| Frozen stimuli T15–T24 | PASS |
| Source identity | PASS |
| Placeholder scan | PASS |
| PDF hashes | PASS |
| TXT hashes | PASS |
| Document hashes | PASS |
| Context capacity | **FAIL** |
| Seed-manifest logic | PASS (unit tests) |

## Source packet

- Order: S1 → S2 → S3 → S4 → S5 (headers unchanged)
- Extraction: `pypdf 5.8.0` text-layer only
- See `SOURCE_QC_REPORT.md`, `SOURCE_HASH_MANIFEST.md`

## Tests

```text
total: 113
passed: 113
failed: 0
coverage: ~70% (pytest-cov over src/config/main)
```

## Explicit non-actions

- No 15-episode instrumentation pilot
- No Anthropic API calls for this freeze
- No source truncation, summarization, reordering, or alternate papers
