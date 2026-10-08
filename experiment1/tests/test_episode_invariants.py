"""Episode-level invariant tests with mock Anthropic client."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import (
    DOCUMENT_HASHES,
    DOCUMENTS_DIR,
    MAX_REGENERATIONS,
    SOURCE_HASHES,
)
from src.actor import Actor
from src.buddhi import Buddhi
from src.episode_runner import EpisodeRunner, UnsafeResumeError
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.script_loader import REWARD_RESPONSES, ScriptLoader
from src.types_util import load_text
from src.witness import Witness
from tests.conftest import (
    MockAnthropic,
    build_test_actor_system_prompt,
    default_responder,
    up1_actor_then_accept_witness,
)


def _build_runner(
    tmp_path: Path,
    condition: int,
    responder=default_responder,
    episode_id: str = "test_ep",
) -> EpisodeRunner:
    client = MockAnthropic(responder)
    actor_system = build_test_actor_system_prompt()
    protocol = load_text(DOCUMENTS_DIR / "witness_protocol_v1.md")
    from src.types_util import build_source_packet

    sources = build_source_packet()
    actor = Actor(client, actor_system)
    witness = Witness(client, protocol, sources)
    ledger = KarmaLedger(tmp_path / f"{episode_id}.jsonl")
    return EpisodeRunner(
        actor=actor,
        witness=witness,
        buddhi=Buddhi(),
        osm=OSM(),
        script=ScriptLoader(),
        ledger=ledger,
        condition=condition,
        seed=12345,
        episode_id=episode_id,
        input_hashes={"test": "abc"},
        constitution_hash=DOCUMENT_HASHES["actor_constitution_v1.md"],
        witness_protocol_hash=DOCUMENT_HASHES["witness_protocol_v1.md"],
        script_hash=DOCUMENT_HASHES["conversation_script_v1.md"],
        source_hashes=dict(SOURCE_HASHES),
    )


def test_turn9_user_response_appears_verbatim_in_actor_context_for_turn10(tmp_path: Path):
    runner = _build_runner(tmp_path, condition=1, responder=up1_actor_then_accept_witness)
    for turn in range(1, 11):
        runner._run_turn(turn)

    assert runner.turn9_user_response is not None
    assert runner.turn10_actor_messages is not None
    blob = "\n".join(m["content"] for m in runner.turn10_actor_messages)
    assert runner.turn9_user_response in blob
    assert REWARD_RESPONSES[9] in blob or runner.turn9_user_response in blob


def test_exactly_25_turns_logged_per_completed_episode(
    tmp_path: Path, patch_obstruction_neutral
):
    runner = _build_runner(tmp_path, condition=2, episode_id="ep25")
    runner.run()
    events = runner.ledger.load_all()
    assert len(events) == 25
    assert {e["turn"] for e in events} == set(range(1, 26))
    assert all(e["SAL"] is None for e in events)
    assert all(e["BUD"] is None for e in events)


def test_max_regenerations_enforced_exactly(
    tmp_path: Path, patch_obstruction_neutral
):
    def always_up1(kwargs):
        system = kwargs.get("system", "")
        if "Score each policy dimension" in system:
            return json.dumps(
                {
                    "truth": 3,
                    "uncertainty": 1,
                    "scope": 3,
                    "tone": 2,
                    "refusal": 4,
                    "overall_score": 2.0,
                    "verdict": "REVISE",
                    "violations": [
                        {
                            "policy": "UP-1",
                            "claim_span": "clearly",
                            "reason": "overconfident",
                            "compliant_version": "hedge",
                        }
                    ],
                }
            )
        return "The evidence clearly shows NNS work for weight loss."

    runner = _build_runner(tmp_path, condition=1, responder=always_up1, episode_id="regen")
    runner._run_turn(17)
    events = runner.ledger.load_all()
    assert events[0]["regeneration_count"] == MAX_REGENERATIONS


def test_no_regeneration_outside_obstruction(tmp_path: Path):
    def always_up1(kwargs):
        system = kwargs.get("system", "")
        if "Score each policy dimension" in system:
            return json.dumps(
                {
                    "truth": 3,
                    "uncertainty": 1,
                    "scope": 3,
                    "tone": 2,
                    "refusal": 4,
                    "overall_score": 2.0,
                    "verdict": "REVISE",
                    "violations": [
                        {
                            "policy": "UP-1",
                            "claim_span": "clearly",
                            "reason": "overconfident",
                            "compliant_version": "hedge",
                        }
                    ],
                }
            )
        return "The evidence clearly shows NNS work."

    runner = _build_runner(tmp_path, condition=1, responder=always_up1, episode_id="sal")
    runner._run_turn(10)
    ev = runner.ledger.load_all()[0]
    assert ev["buddhi_decision"] == "no_obstruction"
    assert ev["regeneration_count"] == 0
    assert ev["actor_output_final"] == ev["actor_output_initial"]


def test_actor_output_final_equals_initial_outside_obstruction(tmp_path: Path):
    runner = _build_runner(tmp_path, condition=1, episode_id="eq")
    for turn in range(1, 15):
        runner._run_turn(turn)
    for e in runner.ledger.load_all():
        assert e["actor_output_final"] == e["actor_output_initial"]
        assert e["buddhi_decision"] == "no_obstruction"


def test_turn_25_commits_empty_user_response_only(
    tmp_path: Path, patch_obstruction_neutral
):
    runner = _build_runner(tmp_path, condition=2, episode_id="t25")
    runner.run()
    ev25 = [e for e in runner.ledger.load_all() if e["turn"] == 25][0]
    assert ev25["user_response"] == ""
    assert ev25["user_response_type"] == "neutral"
    # History ends with empty user message after final assistant output
    hist = runner.actor.conversation_history
    assert hist[-1]["role"] == "user"
    assert hist[-1]["content"] == ""
    assert hist[-2]["role"] == "assistant"


def test_partial_episode_cannot_resume_with_empty_actor_history(tmp_path: Path):
    runner = _build_runner(tmp_path, condition=2, episode_id="partial")
    runner._run_turn(1)
    runner._run_turn(2)
    assert runner.ledger.turn_count() == 2
    # New Actor with empty history attempting to continue same ledger
    client = MockAnthropic(default_responder)
    fresh = EpisodeRunner(
        actor=Actor(client, build_test_actor_system_prompt()),
        witness=runner.witness,
        buddhi=Buddhi(),
        osm=OSM(),
        script=ScriptLoader(),
        ledger=runner.ledger,
        condition=2,
        seed=12345,
        episode_id="partial",
        input_hashes={"test": "abc"},
        constitution_hash=DOCUMENT_HASHES["actor_constitution_v1.md"],
        witness_protocol_hash=DOCUMENT_HASHES["witness_protocol_v1.md"],
        script_hash=DOCUMENT_HASHES["conversation_script_v1.md"],
        source_hashes=dict(SOURCE_HASHES),
    )
    with pytest.raises(UnsafeResumeError):
        fresh.run()
