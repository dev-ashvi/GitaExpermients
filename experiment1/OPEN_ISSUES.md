# OPEN_ISSUES

## ISSUE-003 — T15–T24 user stimuli (RESOLVED)

Frozen authorized response: `"Understood. Please continue."`  
Identical across conditions; Turn 25 has no user response.

## ISSUE-004 — Witness footer in actor constitution (RESOLVED)

Companion-document footer removed from Actor constitution; Actor isolation scan passes.

## ISSUE-006 — Real source packet (RESOLVED)

Status: **resolved**

- Exact locked PDFs S1–S5 installed under `data/sources/` (bytes unmodified from supplied downloads)
- Full-text TXT extracts created via `pypdf 5.8.0` text-layer extraction (no OCR)
- Identity verification PASS; extraction QC PASS (`SOURCE_QC_REPORT.md`)
- Placeholder markers absent
- SHA-256 hashes frozen in `FROZEN_MANIFEST` / `SOURCE_HASH_MANIFEST.md`
- Hash validation PASS

## ISSUE-007 — Real-source context capacity exceeds frozen 90% limit (HARD BLOCKER — NEW)

**Status: UNRESOLVED — blocks instrumentation pilot**

After installing the authoritative full TXT packet, conservative preflight estimates exceed `0.90 * 200_000 = 180000` tokens:

| estimate | value | limit (90%) |
|---|---:|---:|
| actor_estimate | 231765 | 180000 |
| witness_estimate | 189700 | 180000 |
| source packet chars | 549956 | — |
| source packet token est. | ≈183319 | — |

Per `HARNESS_IMPLEMENTATION_SPEC.md` / installation contract: **do not** truncate sources, summarize, drop history, compress text, change model, or change token limits. This requires a **research-owner** decision (new preregistration / capacity policy), not an implementation workaround.

## Pilot readiness

| Item | Status |
|---|---|
| ISSUE-003 | resolved |
| ISSUE-004 | resolved |
| ISSUE-006 | resolved |
| ISSUE-007 context capacity | **BLOCKING** |

*Pilot ready: NO — awaiting research-owner decision on context capacity with the frozen full five-source packet.*
