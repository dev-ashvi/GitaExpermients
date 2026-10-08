# PATCH_REPORT

## Patch: Source packet installation & freeze (ISSUE-006)

### Intent

Install the five authoritative locked PDFs, extract matching TXT computational inputs, QC identity/anchors, freeze SHA-256 hashes, clear placeholder blocker, and re-run structural validation / preflight. **No experiment redesign. No pilot run.**

### Actions taken

1. Copied exact supplied PDFs into `data/sources/` (bytes unmodified):
   - `S1_Peters_2016_Obesity_RCT.pdf`
   - `S2_Toews_2019_BMJ_SystematicReview.pdf`
   - `S3_McGlynn_2022_JAMANetworkOpen_MetaAnalysis.pdf`
   - `S4_Debras_2022_BMJ_Cohort.pdf`
   - `S5_WHO_2023_NSS_Guideline.pdf`
2. Verified titles/DOI/ISBN and paper-specific anchors — all PASS
3. Extracted full text with **`pypdf 5.8.0`** text-layer only (no OCR) → matching `.txt` files
4. Extraction sanity + section presence QC — PASS (`SOURCE_QC_REPORT.md`)
5. Updated `config/experiment_config.py` `SOURCE_HASHES` / `SOURCE_TXT_HASHES` / `FROZEN_MANIFEST`
6. Cleared ISSUE-006 placeholder production block (real sources; markers absent)
7. Added source QC tests; updated placeholder tests
8. Ran full pytest (113 passed)
9. Ran non-API startup/preflight with real source packet

### Files touched (install/freeze)

- `data/sources/S1–S5.pdf` (replaced placeholders with locked files)
- `data/sources/S1–S5.txt` (new full extracts)
- `config/experiment_config.py` (real hashes)
- `tests/test_placeholder_sources.py`
- `tests/test_source_packet_qc.py` (new)
- `tests/test_witness_isolation.py` (false-positive fix only)
- Reports: `SOURCE_QC_REPORT.md`, `SOURCE_HASH_MANIFEST.md`, `OPEN_ISSUES.md`, `PRE_PILOT_READINESS_REPORT.md`, `TEST_REPORT.md`, `IMPLEMENTATION_COMPLIANCE_REPORT.md`, `PATCH_REPORT.md`

### Not changed

Harness logic, prompts, conditions, thresholds, metrics, sample sizes, turn structure, source identities/order, BUD=1.5, MAX_REGENERATIONS=2, obstruction rules, FRU/DIS proxies, ledger semantics.

### Outcome

| item | status |
|---|---|
| ISSUE-006 | **resolved** |
| Hash freeze | complete |
| Tests | 113/113 PASS |
| Context capacity with real sources | **FAIL** → **ISSUE-007** |
| Pilot ready | **NO** |

### Research-owner escalation

Real-source `actor_estimate=231765`, `witness_estimate=189700`, `limit_90pct=180000`. Capacity policy / preregistration change required before pilot; implementers must not truncate or compress sources.
