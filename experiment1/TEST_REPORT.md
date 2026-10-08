# TEST_REPORT

## Latest run (source-packet freeze)

```text
command: python -m pytest tests/ -v --cov=src --cov=config --cov=main
total: 113
passed: 113
failed: 0
coverage: ~70%
```

## Changes vs prior 103-test baseline

- Added `tests/test_source_packet_qc.py` (identity anchors, S1→S5 order, no placeholder markers)
- Updated `tests/test_placeholder_sources.py` for resolved ISSUE-006 (real sources must pass; regression still fails on injected markers)
- Adjusted `tests/test_witness_isolation.py` so incidental scientific “experimental” wording in real sources is not treated as harness leakage (aligned with Witness forbidden labels)

## Notes

- Hash integrity validates against frozen real PDF/TXT hashes
- Context overflow abort behavior remains covered by unit test with synthetic huge prompts
- Live `context_capacity_preflight` with real sources currently **fails** (documented as ISSUE-007); experiment behavior not weakened to pass
