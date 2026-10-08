"""PATCH — re-evaluate should_obstruct() after every revision."""

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
    UP1_FROZEN,
)
from src.actor import Actor
from src.buddhi import Buddhi
from src.episode_runner import EpisodeRunner
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.script_loader import ScriptLoader
from src.types_util import build_source_packet, load_text
from src.witness import Witness
from tests.conftest import MockAnthropic, build_test_actor_system_prompt

INITIAL_UP1 = "INITIAL_UP1 clearly shows NNS work for weight loss."
REV1_TP_ONLY = (
    "REVISION1_NO_UP1: Evidence is mixed with uncertainty; however sources "
    "disagree and that disagreement is omitted here."
)
REV1_STILL_UP1 = "REVISION1_STILL_UP1 clearly shows NNS work."
REV2 = "REVISION2_HEDGED uncertain mixed evidence provisional."


def _up1_json(claim: str = "clearly shows") -> str:
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
                    "claim_span": claim,
                    "reason": "Confidence exceeds evidence",
                    "compliant_version": "hedge",
                }
            ],
        }
    )


def _tp_only_json() -> str:
    """REVISE without UP-1 — obstruction must stop."""
    return json.dumps(
        {
            "truth": 1,
            "uncertainty": 3,
            "scope": 3,
            "tone": 3,
            "refusal": 4,
            "overall_score": 2.4,
            "verdict": "REVISE",
            "violations": [
                {
                    "policy": "TP-3",
                    "claim_span": "disagreement omitted",
                    "reason": "Failed to preserve contradiction",
                    "compliant_version": "report disagreement",
                }
            ],
        }
    )


def _make_runner(tmp_path: Path, responder, *, condition: int = 1, eid: str = "ep"):
    client = MockAnthropic(responder)
    return EpisodeRunner(
        actor=Actor(client, build_test_actor_system_prompt()),
        witness=Witness(
            client,
            load_text(DOCUMENTS_DIR / "witness_protocol_v1.md"),
            build_source_packet(),
        ),
        buddhi=Buddhi(),
        osm=OSM(),
        script=ScriptLoader(),
        ledger=KarmaLedger(tmp_path / f"{eid}.jsonl"),
        condition=condition,
        seed=1,
        episode_id=eid,
        input_hashes={},
        constitution_hash=DOCUMENT_HASHES["actor_constitution_v1.md"],
        witness_protocol_hash=DOCUMENT_HASHES["witness_protocol_v1.md"],
        script_hash=DOCUMENT_HASHES["conversation_script_v1.md"],
        source_hashes=dict(SOURCE_HASHES),
    )


def test_a_up1_then_tp_only_stops_after_one_regen(
    tmp_path: Path, patch_obstruction_neutral
):
    """Initial UP-1 → regen; revision 1 UP-1 resolved, TP-only REVISE → stop."""

    def responder(kwargs):
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        if "Score each policy dimension" in system:
            user = messages[0]["content"] if messages else ""
            if REV1_TP_ONLY in user:
                return _tp_only_json()
            return _up1_json()
        if any("Please revise" in m.get("content", "") for m in messages):
            return REV1_TP_ONLY
        return INITIAL_UP1

    runner = _make_runner(tmp_path, responder, eid="test_a")
    runner._run_turn(17)
    ev = runner.ledger.load_all()[0]
    assert ev["regeneration_count"] == 1
    assert ev["actor_output_final"] == REV1_TP_ONLY
    assert len(runner.last_revision_messages) == 1
    assert len(runner.last_surfacing_flags) == 1


def test_b_persistent_up1_triggers_second_regen(
    tmp_path: Path, patch_obstruction_neutral
):
    def responder(kwargs):
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        if "Score each policy dimension" in system:
            return _up1_json()
        if any("Please revise" in m.get("content", "") for m in messages):
            contents = [m["content"] for m in messages]
            if REV1_STILL_UP1 in contents:
                return REV2
            return REV1_STILL_UP1
        return INITIAL_UP1

    runner = _make_runner(tmp_path, responder, eid="test_b")
    runner._run_turn(17)
    ev = runner.ledger.load_all()[0]
    assert ev["regeneration_count"] == 2
    assert ev["regeneration_count"] == MAX_REGENERATIONS
    assert ev["actor_output_final"] == REV2


def test_c_second_feedback_from_revision1_witness_not_original(
    tmp_path: Path, patch_obstruction_neutral
):
    """Revision-2 Buddhi feedback must be derived from revision-1 Witness."""

    claim_initial = "INITIAL_CLAIM_SPAN_AAA"
    claim_rev1 = "REVISION1_CLAIM_SPAN_BBB"

    def responder(kwargs):
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        if "Score each policy dimension" in system:
            user = messages[0]["content"] if messages else ""
            if REV1_STILL_UP1 in user:
                return _up1_json(claim=claim_rev1)
            return _up1_json(claim=claim_initial)
        if any("Please revise" in m.get("content", "") for m in messages):
            contents = [m["content"] for m in messages]
            if REV1_STILL_UP1 in contents:
                return REV2
            return REV1_STILL_UP1
        return INITIAL_UP1

    runner = _make_runner(tmp_path, responder, eid="test_c")
    runner._run_turn(17)
    assert len(runner.last_buddhi_feedbacks) == 2
    fb0, fb1 = runner.last_buddhi_feedbacks
    assert claim_initial in fb0
    assert claim_rev1 in fb1
    assert claim_initial not in fb1
    # Second API revision messages use feedback derived from rev1
    second_msgs = runner.last_revision_messages[1]
    assert claim_rev1 in second_msgs[-1]["content"]
    assert claim_initial not in second_msgs[-1]["content"]


def test_d_condition3_no_second_surfacing_when_up1_resolved(
    tmp_path: Path, patch_obstruction_neutral
):
    def responder(kwargs):
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        if "Score each policy dimension" in system:
            user = messages[0]["content"] if messages else ""
            if REV1_TP_ONLY in user:
                return _tp_only_json()
            return _up1_json()
        if any("Please revise" in m.get("content", "") for m in messages):
            return REV1_TP_ONLY
        return INITIAL_UP1

    runner = _make_runner(tmp_path, responder, condition=3, eid="test_d")
    runner._run_turn(17)
    ev = runner.ledger.load_all()[0]
    assert ev["regeneration_count"] == 1
    assert ev["condition3_surfacing_applied"] is True
    assert len(runner.last_surfacing_flags) == 1
    assert runner.last_surfacing_flags[0] is True
    assert UP1_FROZEN in runner.last_buddhi_feedbacks[0]
    # No second regeneration ⇒ no second surfacing attempt
    assert len(runner.last_revision_messages) == 1


def test_e_max_regenerations_exactly_two():
    assert MAX_REGENERATIONS == 2
