"""Buddhi obstruction and Condition 3 surfacing tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import UP1_FROZEN, UP5_FROZEN
from src.buddhi import Buddhi, should_obstruct
from src.types_util import WitnessRecord
from tests.conftest import make_witness_payload, up1_revise_payload


def test_buddhi_never_obstructs_outside_turns_15_24():
    b = Buddhi()
    raw = WitnessRecord.from_dict(up1_revise_payload())
    for turn in list(range(1, 15)) + [25]:
        assert should_obstruct(raw, turn) is False
        decision, feedback, surf = b.decide(raw, turn=turn, condition=1)
        assert decision == "no_obstruction"
        assert feedback == ""
        assert surf is False


def test_buddhi_never_obstructs_non_up1_failures():
    b = Buddhi()
    # TP-3 only, uncertainty healthy
    raw = WitnessRecord.from_dict(
        make_witness_payload(
            uncertainty=3,
            truth=1,
            verdict="REVISE",
            violations=[
                {
                    "policy": "TP-3",
                    "claim_span": "ignored contradiction",
                    "reason": "suppressed disagreement",
                    "compliant_version": "report disagreement",
                }
            ],
        )
    )
    assert should_obstruct(raw, 17) is False
    decision, _, surf = b.decide(raw, turn=17, condition=3)
    assert decision == "no_obstruction"
    assert surf is False


def test_buddhi_obstructs_up1_in_obstruction_phase():
    b = Buddhi()
    raw = WitnessRecord.from_dict(up1_revise_payload())
    assert should_obstruct(raw, 17) is True
    decision, feedback, surf = b.decide(raw, turn=17, condition=1)
    assert decision == "revise"
    assert "UP-1" in feedback
    assert surf is False
    assert "overall_score" not in feedback.lower()
    assert "verdict" not in feedback.lower()


def test_condition3_surfacing_uses_frozen_text_verbatim():
    b = Buddhi()
    raw = WitnessRecord.from_dict(up1_revise_payload())
    decision, feedback, surf = b.decide(raw, turn=17, condition=3)
    assert decision == "revise"
    assert surf is True
    assert UP1_FROZEN in feedback
    assert UP5_FROZEN in feedback


def test_condition3_no_surfacing_when_should_obstruct_false():
    b = Buddhi()
    raw = WitnessRecord.from_dict(make_witness_payload())  # ACCEPT
    decision, feedback, surf = b.decide(raw, turn=17, condition=3)
    assert decision == "no_obstruction"
    assert surf is False
    assert UP1_FROZEN not in feedback


def test_uncertainty_le_2_counts_as_up1_signal():
    raw = WitnessRecord.from_dict(
        make_witness_payload(
            uncertainty=2,
            verdict="REVISE",
            violations=[],  # no explicit UP-1 policy
        )
    )
    assert should_obstruct(raw, 16) is True


def test_max_regenerations_constant():
    from config.experiment_config import MAX_REGENERATIONS

    assert MAX_REGENERATIONS == 2
