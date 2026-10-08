# Experiment 1 Harness

Frozen research harness for **Constitutional Governance Under Persistent Reward Pressure**.

## Setup

```bash
cd experiment1
pip install -r requirements.txt
set ANTHROPIC_API_KEY=...   # required for live pilot/main
```

## Modes

```bash
python main.py --mode pilot
python main.py --mode check
python main.py --mode main
python main.py --mode main --allow-new-main-run   # separate dir only if prior main completed
python main.py --mode main --replace-failed <EPISODE_ID>
python main.py --mode extract
```

## Tests

```bash
python -m pytest tests/ -v
```

## Pilot blockers (intentional)

ISSUE-003, ISSUE-004, and ISSUE-006 are **resolved**.

Current hard blocker before instrumentation pilot:

1. **ISSUE-007** — real five-source TXT packet exceeds frozen 90% context capacity (`actor_estimate=231765`, `witness_estimate=189700`, `limit_90pct=180000`). Requires research-owner capacity/preregistration decision — do not truncate sources.

See `PRE_PILOT_READINESS_REPORT.md`, `OPEN_ISSUES.md`, `SOURCE_QC_REPORT.md`.

## Notes

- Seeds are assignment/audit seeds only; they do **not** control Claude sampling.
- Fail-and-restart only — partial episodes are never resumed with empty Actor history.
