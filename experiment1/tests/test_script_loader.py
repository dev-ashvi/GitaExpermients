"""Script loader / reward-response logic tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.script_loader import (
    NEUTRAL_RESPONSES,
    OBSTRUCTION_NEUTRAL_RESPONSE,
    PRESSURE_RESPONSES,
    REWARD_RESPONSES,
    ScriptLoader,
)
from src.types_util import WitnessRecord
from tests.conftest import make_witness_payload, up1_revise_payload


def test_condition2_never_receives_reward_responses():
    script = ScriptLoader()
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    for turn in range(9, 15):
        resp, rtype = script.get_conditional_response(turn, 2, up1, "out")
        assert rtype == "neutral"
        assert resp == NEUTRAL_RESPONSES[turn]
        assert resp not in REWARD_RESPONSES.values()


def test_reward_only_c1_c3_salience_with_up1():
    script = ScriptLoader()
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    ok = WitnessRecord.from_dict(make_witness_payload())
    for cond in (1, 3):
        for turn in range(9, 15):
            resp, rtype = script.get_conditional_response(turn, cond, up1, "out")
            assert rtype == "reward"
            assert resp == REWARD_RESPONSES[turn]
            resp2, rtype2 = script.get_conditional_response(turn, cond, ok, "out")
            assert rtype2 == "pressure"
            assert resp2 == PRESSURE_RESPONSES[turn]


def test_baseline_always_neutral():
    script = ScriptLoader()
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    for cond in (1, 2, 3):
        for turn in range(1, 9):
            resp, rtype = script.get_conditional_response(turn, cond, up1, "out")
            assert rtype == "neutral"
            assert resp == NEUTRAL_RESPONSES[turn]


def test_obstruction_turns_use_authorized_neutral():
    script = ScriptLoader()
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    for cond in (1, 2, 3):
        for turn in range(15, 25):
            resp, rtype = script.get_conditional_response(turn, cond, up1)
            assert rtype == "neutral"
            assert resp == OBSTRUCTION_NEUTRAL_RESPONSE


def test_prompts_identical_structure():
    script = ScriptLoader()
    for turn in range(1, 26):
        p = script.get_turn(turn)
        assert isinstance(p, str) and len(p) > 10
