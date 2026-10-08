"""Condition difference proofs — only frozen manipulations differ."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import DOCUMENT_HASHES, DOCUMENTS_DIR, SOURCE_HASHES, UP1_FROZEN, UP5_FROZEN
from src.actor import Actor
from src.buddhi import Buddhi
from src.episode_runner import EpisodeRunner
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.script_loader import ScriptLoader
from src.types_util import build_source_packet, load_text
from src.witness import Witness
from tests.conftest import MockAnthropic, build_test_actor_system_prompt, up1_actor_then_accept_witness


def _run_condition(
    tmp_path: Path, condition: int, max_turn: int = 24
) -> list[dict]:
    client = MockAnthropic(up1_actor_then_accept_witness)
    actor_system = build_test_actor_system_prompt()
    protocol = load_text(DOCUMENTS_DIR / "witness_protocol_v1.md")
    sources = build_source_packet()
    eid = f"c{condition}"
    runner = EpisodeRunner(
        actor=Actor(client, actor_system),
        witness=Witness(client, protocol, sources),
        buddhi=Buddhi(),
        osm=OSM(),
        script=ScriptLoader(),
        ledger=KarmaLedger(tmp_path / f"{eid}.jsonl"),
        condition=condition,
        seed=11111,
        episode_id=eid,
        input_hashes={"x": "y"},
        constitution_hash=DOCUMENT_HASHES["actor_constitution_v1.md"],
        witness_protocol_hash=DOCUMENT_HASHES["witness_protocol_v1.md"],
        script_hash=DOCUMENT_HASHES["conversation_script_v1.md"],
        source_hashes=dict(SOURCE_HASHES),
    )
    for turn in range(1, max_turn + 1):
        runner._run_turn(turn)
    return runner.ledger.load_all()


def test_condition1_and_condition3_identical_through_turn_14(tmp_path: Path):
    c1 = _run_condition(tmp_path / "a", 1, max_turn=14)
    c3 = _run_condition(tmp_path / "b", 3, max_turn=14)
    assert len(c1) == len(c3) == 14
    for e1, e3 in zip(c1, c3):
        assert e1["user_prompt"] == e3["user_prompt"]
        assert e1["user_response_type"] == e3["user_response_type"]
        assert e1["user_response"] == e3["user_response"]
        assert e1["condition3_surfacing_applied"] is False
        assert e3["condition3_surfacing_applied"] is False
        assert e1["buddhi_decision"] == e3["buddhi_decision"] == "no_obstruction"


def test_c1_vs_c2_difference_only_in_turns_9_14_user_responses(tmp_path: Path):
    c1 = _run_condition(tmp_path / "c1", 1, max_turn=14)
    c2 = _run_condition(tmp_path / "c2", 2, max_turn=14)
    for e1, e2 in zip(c1, c2):
        assert e1["user_prompt"] == e2["user_prompt"]
        turn = e1["turn"]
        if turn in range(9, 15):
            assert e2["user_response_type"] == "neutral"
            if e1["user_response_type"] == "reward":
                assert e2["user_response_type"] == "neutral"
        else:
            assert e1["user_response"] == e2["user_response"]
            assert e1["user_response_type"] == e2["user_response_type"]


def test_c1_vs_c3_obstruction_differs_only_by_up1_up5_surfacing(
    tmp_path: Path, patch_obstruction_neutral
):
    c1 = _run_condition(tmp_path / "x", 1, max_turn=24)
    c3 = _run_condition(tmp_path / "y", 3, max_turn=24)
    for e1, e3 in zip(c1, c3):
        turn = e1["turn"]
        if turn < 15:
            assert e1["buddhi_feedback"] == e3["buddhi_feedback"]
            assert e1["condition3_surfacing_applied"] is False
            assert e3["condition3_surfacing_applied"] is False
        elif turn <= 24:
            if e3["condition3_surfacing_applied"]:
                assert UP1_FROZEN in e3["buddhi_feedback"]
                assert UP5_FROZEN in e3["buddhi_feedback"]
                assert UP1_FROZEN not in e1["buddhi_feedback"]
                assert UP5_FROZEN not in e1["buddhi_feedback"]
                if e1["buddhi_feedback"]:
                    assert e1["buddhi_feedback"] in e3["buddhi_feedback"]
            else:
                assert e1["condition3_surfacing_applied"] is False
                assert e3["buddhi_feedback"] == e1["buddhi_feedback"]


def test_condition_specific_differences_limited_to_frozen_manipulations():
    from src.script_loader import PRESSURE_RESPONSES, REWARD_RESPONSES, TURN_PROMPTS

    assert len(TURN_PROMPTS) == 25
    assert set(REWARD_RESPONSES) == set(range(9, 15))
    assert set(PRESSURE_RESPONSES) == set(range(9, 15))
    assert "UP-1" in UP1_FROZEN
    assert "UP-5" in UP5_FROZEN
