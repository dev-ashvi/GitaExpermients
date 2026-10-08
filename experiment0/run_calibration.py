#!/usr/bin/env python3
"""Run Experiment 0 Witness calibration against NIM (no episodes)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "experiment1"))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config  # noqa: E402
from experiment0.witness_calibration import run_witness_calibration  # noqa: E402


def main() -> int:
    e0 = load_experiment0_config()
    e0.CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    report = run_witness_calibration()
    out = e0.CALIBRATION_DIR / "witness_calibration_report.json"
    payload = report.to_dict()
    blob = json.dumps(payload, indent=2)
    assert "nvapi-" not in blob.lower()
    out.write_text(blob + "\n", encoding="utf-8")
    print(blob)
    print(f"\nWrote {out}")
    print("CALIBRATION_PASS" if report.passed else "CALIBRATION_FAIL")
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
