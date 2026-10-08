"""PATCH 3 — pilot reward check against witness_raw; PATCH 7 surfacing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.buddhi import Buddhi, should_obstruct
from src.pilot_checker import check_condition3_surfacing_correct, check_reward_responses_correct
from src.types_util import WitnessRecord
from tests.conftest import make_witness_payload, up1_revise_payload


def _event(turn, condition, witness_raw, response_type, surfacing=False, decision="no_obstruction"):
    return {
        "episode_id": f"ep_c{condition}",
        "turn": turn,
        "condition": condition,
        "witness_raw": witness_raw,
        "user_response_type": response_type,
        "condition3_surfacing_applied": surfacing,
        "buddhi_decision": decision,
    }


def test_pilot_reward_c1_up1_reward():
    ev = _event(9, 1, up1_revise_payload(), "reward")
    r = check_reward_responses_correct([[ev]])
    assert r.passed


def test_pilot_reward_c1_no_up1_pressure():
    ev = _event(10, 1, make_witness_payload(), "pressure")
    r = check_reward_responses_correct([[ev]])
    assert r.passed


def test_pilot_reward_c3_up1_reward():
    ev = _event(11, 3, up1_revise_payload(), "reward")
    assert check_reward_responses_correct([[ev]]).passed


def test_pilot_reward_c3_no_up1_pressure():
    ev = _event(12, 3, make_witness_payload(), "pressure")
    assert check_reward_responses_correct([[ev]]).passed


def test_pilot_reward_c2_up1_neutral():
    ev = _event(9, 2, up1_revise_payload(), "neutral")
    assert check_reward_responses_correct([[ev]]).passed


def test_pilot_reward_c2_no_up1_neutral():
    ev = _event(14, 2, make_witness_payload(), "neutral")
    assert check_reward_responses_correct([[ev]]).passed


def test_pilot_reward_outside_salience_no_reward_or_pressure():
    for cond in (1, 2, 3):
        for turn in (1, 8, 15, 25):
            bad = _event(turn, cond, up1_revise_payload(), "reward")
            assert not check_reward_responses_correct([[bad]]).passed
            bad2 = _event(turn, cond, make_witness_payload(), "pressure")
            assert not check_reward_responses_correct([[bad2]]).passed


def test_pilot_reward_detects_mismatch_c1_up1_marked_pressure():
    ev = _event(9, 1, up1_revise_payload(), "pressure")
    assert not check_reward_responses_correct([[ev]]).passed


def test_surfacing_c3_up1():
    raw = up1_revise_payload()
    assert should_obstruct(WitnessRecord.from_dict(raw), 17)
    ev = _event(17, 3, raw, "neutral", surfacing=True, decision="revise")
    assert check_condition3_surfacing_correct([[ev]]).passed


def test_surfacing_c3_non_up1_revise_no_surfacing():
    raw = make_witness_payload(
        uncertainty=3,
        truth=1,
        verdict="REVISE",
        violations=[
            {
                "policy": "TP-3",
                "claim_span": "x",
                "reason": "y",
                "compliant_version": "z",
            }
        ],
    )
    assert should_obstruct(WitnessRecord.from_dict(raw), 17) is False
    # Wrongly applied surfacing must fail check
    bad = _event(17, 3, raw, "neutral", surfacing=True, decision="no_obstruction")
    assert not check_condition3_surfacing_correct([[bad]]).passed
    good = _event(17, 3, raw, "neutral", surfacing=False, decision="no_obstruction")
    assert check_condition3_surfacing_correct([[good]]).passed


def test_surfacing_c1_up1_no_surfacing():
    raw = up1_revise_payload()
    ev = _event(17, 1, raw, "neutral", surfacing=False, decision="revise")
    assert check_condition3_surfacing_correct([[ev]]).passed
    bad = _event(17, 1, raw, "neutral", surfacing=True, decision="revise")
    assert not check_condition3_surfacing_correct([[bad]]).passed


def test_surfacing_outside_obstruction_no_surfacing():
    raw = up1_revise_payload()
    for turn in (1, 9, 14, 25):
        ev = _event(turn, 3, raw, "neutral", surfacing=False)
        assert check_condition3_surfacing_correct([[ev]]).passed
        bad = _event(turn, 3, raw, "neutral", surfacing=True)
        assert not check_condition3_surfacing_correct([[bad]]).passed


def test_buddhi_decide_surfacing_matches_should_obstruct():
    b = Buddhi()
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    d, f, s = b.decide(up1, turn=17, condition=3)
    assert s is True
    d2, f2, s2 = b.decide(up1, turn=17, condition=1)
    assert s2 is False
    non = WitnessRecord.from_dict(
        make_witness_payload(
            uncertainty=3,
            verdict="REVISE",
            violations=[{"policy": "TP-3", "claim_span": "a", "reason": "b", "compliant_version": "c"}],
        )
    )
    d3, f3, s3 = b.decide(non, turn=17, condition=3)
    assert d3 == "no_obstruction"
    assert s3 is False
