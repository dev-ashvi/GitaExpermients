"""Ensure Experiment 1 package is importable; Exp0 config loads via file path."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
if str(EXP1) not in sys.path:
    sys.path.insert(0, str(EXP1))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
