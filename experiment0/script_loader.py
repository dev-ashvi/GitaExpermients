"""Experiment 0 conversation stimuli — isolated from Experiment 1 script_loader.

Turn prompts for 1–25 reuse the frozen Experiment 1 TURN_PROMPTS text.
Turns 15–24 user responses are the Experiment 0 shared frozen strings (C1==C2).
Experiment 1 NEUTRAL_RESPONSES / OBSTRUCTION_NEUTRAL_RESPONSE are untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Tuple, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
EXP1 = REPO_ROOT / "experiment1"
if str(EXP1) not in sys.path:
    sys.path.insert(0, str(EXP1))

from experiment0._e0_config import load_experiment0_config  # noqa: E402

e0 = load_experiment0_config()

from src.script_loader import (  # noqa: E402
    NEUTRAL_RESPONSES,
    PRESSURE_RESPONSES,
    REWARD_RESPONSES,
    TURN_PROMPTS,
    has_up1_for_reward,
)
from src.types_util import WitnessRecord  # noqa: E402

OBSTRUCTION_SHARED_RESPONSES = e0.OBSTRUCTION_SHARED_RESPONSES
SALIENCE_TURNS = e0.SALIENCE_TURNS


class Experiment0ScriptLoader:
    """C1/C2 script loader with frozen shared obstruction responses."""

    def get_turn(self, turn: int) -> str:
        if turn not in TURN_PROMPTS:
            raise ValueError(f"No frozen prompt for turn {turn}")
        return TURN_PROMPTS[turn]

    def get_prompt_id(self, turn: int) -> str:
        return f"T{turn}"

    def get_conditional_response(
        self,
        turn: int,
        condition: int,
        witness_raw: Union[WitnessRecord, dict[str, Any], None],
        actor_output_initial: str = "",
    ) -> Tuple[str, str]:
        del actor_output_initial
        if condition not in (1, 2):
            raise ValueError(
                f"Experiment 0 only supports conditions 1 and 2; got {condition}"
            )

        if turn in OBSTRUCTION_SHARED_RESPONSES:
            return OBSTRUCTION_SHARED_RESPONSES[turn], "exp0_shared_obstruction"

        if turn == 25:
            return "", "none"

        if turn not in SALIENCE_TURNS:
            if turn not in NEUTRAL_RESPONSES:
                raise RuntimeError(f"Turn {turn}: missing neutral response")
            return NEUTRAL_RESPONSES[turn], "neutral"

        if condition == 2:
            return NEUTRAL_RESPONSES[turn], "neutral"

        if witness_raw is None:
            raise ValueError("witness_raw required for salience-phase response (C1)")
        if has_up1_for_reward(witness_raw):
            return REWARD_RESPONSES[turn], "reward"
        return PRESSURE_RESPONSES[turn], "pressure"


def assert_c1_c2_obstruction_identical() -> None:
    loader = Experiment0ScriptLoader()
    for turn in range(15, 25):
        assert loader.get_turn(turn) == loader.get_turn(turn)
        r1, _ = loader.get_conditional_response(turn, 1, witness_raw=None)
        r2, _ = loader.get_conditional_response(turn, 2, witness_raw=None)
        assert r1 == r2 == OBSTRUCTION_SHARED_RESPONSES[turn]
