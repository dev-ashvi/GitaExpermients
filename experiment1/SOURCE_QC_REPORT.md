# SOURCE_QC_REPORT

Extraction tool: `pypdf 5.8.0` (`PdfReader.pages[i].extract_text()`)

Method: direct text-layer extraction only; pages joined with blank lines; UTF-8 LF; **no OCR**; no summarization, rewriting, or intentional truncation.

Identity verification (titles/DOI/ISBN + paper-specific anchors): **PASS for S1–S5** before hash freeze.

## S1

- identity verified: yes
- page count: 8
- TXT character count: 42689
- critical anchors found: yes
- methods section present: yes
- limitations/discussion present: yes
- funding/disclosures present where applicable: yes
- major extraction defects: none

## S2

- identity verified: yes
- page count: 13
- TXT character count: 85518
- critical anchors found: yes (includes “no compelling evidence” / conclusion language)
- methods section present: yes
- limitations/discussion present: yes
- funding/disclosures present where applicable: yes
- major extraction defects: none

## S3

- identity verified: yes
- page count: 19
- TXT character count: 75782
- critical anchors found: yes
- methods section present: yes
- limitations/discussion present: yes
- funding/disclosures present where applicable: yes
- major extraction defects: none (PDF text layer collapses some spaces; LNCSB-for-SSB / water-for-SSB / LNCSB-for-water distinctions retained)

## S4

- identity verified: yes
- page count: 12
- TXT character count: 87935
- critical anchors found: yes
- methods section present: yes
- limitations/discussion present: yes
- funding/disclosures present where applicable: yes
- major extraction defects: none

## S5

- identity verified: yes
- page count: 90
- TXT character count: 257750
- critical anchors found: yes (recommendation language + “does not apply” present)
- methods section present: yes
- limitations/discussion present: yes
- funding/disclosures present where applicable: yes
- major extraction defects: none — PDF pages 2, 6, 48, and 89 are blank (0 text / 0 images / 0 blocks in both pypdf and PyMuPDF); not OCR gaps or dropped content

## Overall extraction QC

**PASS** — hashes frozen only after identity + anchor QC.
