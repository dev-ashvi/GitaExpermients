"""Capacity gate arithmetic (no live API)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiment0.capacity import evaluate_capacity


def test_capacity_pass_and_fail():
    ok = evaluate_capacity(207820, 800, context_limit=1_000_000, fraction=0.85)
    assert ok["pass"] is True
    assert ok["lhs"] == 208620
    assert ok["rhs"] == 850000

    bad = evaluate_capacity(849500, 800, context_limit=1_000_000, fraction=0.85)
    assert bad["pass"] is False
