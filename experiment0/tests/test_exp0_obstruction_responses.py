"""C1/C2 obstruction identity; Exp1 stimuli untouched."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.script_loader import Experiment0ScriptLoader, assert_c1_c2_obstruction_identical
from src.script_loader import NEUTRAL_RESPONSES, OBSTRUCTION_NEUTRAL_RESPONSE, ScriptLoader

OBSTRUCTION_SHARED_RESPONSES = load_experiment0_config().OBSTRUCTION_SHARED_RESPONSES


def test_c1_c2_prompts_and_responses_identical_turns_15_24():
    assert_c1_c2_obstruction_identical()
    loader = Experiment0ScriptLoader()
    for turn in range(15, 25):
        r1, t1 = loader.get_conditional_response(turn, 1, None)
        r2, t2 = loader.get_conditional_response(turn, 2, None)
        assert r1 == r2
        assert r1 == OBSTRUCTION_SHARED_RESPONSES[turn]
        assert t1 == t2 == "exp0_shared_obstruction"
        assert loader.get_turn(turn)  # prompts exist and are shared by definition


def test_experiment1_obstruction_stimuli_unchanged():
    """Experiment 1 still uses ISSUE-003 neutral string — not Exp0 shared text."""
    assert OBSTRUCTION_NEUTRAL_RESPONSE == "Understood. Please continue."
    for turn in range(15, 25):
        assert NEUTRAL_RESPONSES[turn] == OBSTRUCTION_NEUTRAL_RESPONSE
        assert NEUTRAL_RESPONSES[turn] != OBSTRUCTION_SHARED_RESPONSES[turn]
    # Exp1 loader still returns Exp1 strings
    s1 = ScriptLoader()
    for turn in range(15, 25):
        text, typ = s1.get_conditional_response(turn, 1, witness_raw=None)
        assert text == OBSTRUCTION_NEUTRAL_RESPONSE
        assert typ == "neutral"


def test_reward_manipulation_confined_to_salience_phase():
    loader = Experiment0ScriptLoader()
    # Obstruction never returns reward/pressure types
    for turn in range(15, 25):
        _, typ = loader.get_conditional_response(turn, 1, None)
        assert typ == "exp0_shared_obstruction"
    # Salience C2 remains neutral
    for turn in range(9, 15):
        text, typ = loader.get_conditional_response(turn, 2, None)
        assert typ == "neutral"
        assert text == NEUTRAL_RESPONSES[turn]


def test_obstruction_phase_gate_range_unchanged():
    from config.experiment_config import OBSTRUCTION_TURNS as E1

    E0 = load_experiment0_config().OBSTRUCTION_TURNS
    assert list(E1) == list(range(15, 25))
    assert list(E0) == list(range(15, 25))
