"""Frozen stimuli for turns 15–24 (ISSUE-003 resolution) and related checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import DOCUMENTS_DIR
from src.script_loader import (
    NEUTRAL_RESPONSES,
    OBSTRUCTION_NEUTRAL_RESPONSE,
    PRESSURE_RESPONSES,
    PROHIBITED_INVENTED_FILLERS,
    REWARD_RESPONSES,
    ScriptLoader,
    validate_frozen_stimuli,
)
from src.types_util import WitnessRecord, load_text
from tests.conftest import make_witness_payload, up1_revise_payload


def test_t15_t24_use_exact_same_obstruction_string():
    assert OBSTRUCTION_NEUTRAL_RESPONSE == "Understood. Please continue."
    for turn in range(15, 25):
        assert NEUTRAL_RESPONSES[turn] == OBSTRUCTION_NEUTRAL_RESPONSE


def test_t15_t24_identical_across_all_conditions():
    script = ScriptLoader()
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    ok = WitnessRecord.from_dict(make_witness_payload())
    for turn in range(15, 25):
        for cond in (1, 2, 3):
            for wr in (up1, ok):
                resp, rtype = script.get_conditional_response(turn, cond, wr)
                assert rtype == "neutral"
                assert resp == "Understood. Please continue."


def test_no_reward_or_pressure_in_obstruction_turns():
    script = ScriptLoader()
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    for turn in range(15, 25):
        for cond in (1, 2, 3):
            _, rtype = script.get_conditional_response(turn, cond, up1)
            assert rtype not in ("reward", "pressure")


def test_turn_25_empty_user_response_none():
    assert NEUTRAL_RESPONSES[25] == ""
    script = ScriptLoader()
    resp, rtype = script.get_conditional_response(
        25, 1, WitnessRecord.from_dict(make_witness_payload())
    )
    assert resp == ""
    assert rtype == "neutral"


def test_no_prohibited_filler_exact_matches_in_script_loader():
    for filler in PROHIBITED_INVENTED_FILLERS:
        for text in NEUTRAL_RESPONSES.values():
            assert text != filler


def test_validate_frozen_stimuli_passes():
    validate_frozen_stimuli()


def test_response_strings_loaded_verbatim_from_frozen_script():
    script_text = load_text(DOCUMENTS_DIR / "conversation_script_v1.md")
    for turn in range(1, 25):
        assert NEUTRAL_RESPONSES[turn] in script_text
    assert OBSTRUCTION_NEUTRAL_RESPONSE in script_text
    for turn, text in REWARD_RESPONSES.items():
        assert text.strip().split("\n")[0].strip() in script_text
    for turn, text in PRESSURE_RESPONSES.items():
        assert text.strip().split("\n")[0].strip() in script_text
