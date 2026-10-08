"""Witness output-budget instrumentation invariants (Exp0 vs Exp1)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.capacity import evaluate_capacity


def test_exp0_witness_uses_calibrated_budget():
    e0 = load_experiment0_config()
    assert e0.MAX_TOKENS_WITNESS == 1600
    assert e0.MAX_TOKENS_WITNESS_ORIGINAL == 600
    assert e0.MAX_TOKENS_ACTOR == 800


def test_exp1_witness_budget_unchanged():
    from config.experiment_config import MAX_TOKENS_ACTOR, MAX_TOKENS_WITNESS

    assert MAX_TOKENS_WITNESS == 600
    assert MAX_TOKENS_ACTOR == 800


def test_capacity_preflight_uses_exp0_witness_budget():
    e0 = load_experiment0_config()
    # Arithmetic must reserve the calibrated Witness budget
    result = evaluate_capacity(
        170414,
        e0.MAX_TOKENS_WITNESS,
        context_limit=e0.MODEL_CONTEXT_LIMIT,
        fraction=e0.CONTEXT_CAPACITY_FRACTION,
    )
    assert result["reserved_output"] == 1600
    assert result["lhs"] == 170414 + 1600
    assert result["rhs"] == 850000
    assert result["pass"] is True
