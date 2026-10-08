"""PATCH 1 — Buddhi regeneration context must include the candidate being revised."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import DOCUMENT_HASHES, DOCUMENTS_DIR, SOURCE_HASHES
from src.actor import Actor
from src.buddhi import Buddhi
from src.episode_runner import EpisodeRunner
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.script_loader import ScriptLoader
from src.types_util import build_source_packet, load_text
from src.witness import Witness
from tests.conftest import MockAnthropic, build_test_actor_system_prompt


INITIAL = "INITIAL_CANDIDATE_UNIQUE_STRING clearly shows NNS work."
REVISION_1 = "REVISION_ONE_UNIQUE_STRING still too confident clearly shows."
REVISION_2 = "REVISION_TWO_UNIQUE_STRING hedged uncertain mixed evidence."


def _responder(kwargs):
    system = kwargs.get("system", "")
    messages = kwargs.get("messages", [])
    if "Score each policy dimension" in system:
        # Always REVISE so both regenerations fire
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
    # Actor path: detect whether this is revision (assistant candidate present)
    roles = [m["role"] for m in messages]
    if roles.count("assistant") >= 1 and any(
        "Please revise" in m.get("content", "") for m in messages
    ):
        # Second revision if revision-1 already in candidate slot
        contents = [m["content"] for m in messages]
        if REVISION_1 in contents:
            return REVISION_2
        return REVISION_1
    return INITIAL


def test_regeneration_payload_includes_candidate_and_feedback(
    tmp_path: Path, patch_obstruction_neutral
):
    client = MockAnthropic(_responder)
    runner = EpisodeRunner(
        actor=Actor(client, build_test_actor_system_prompt()),
        witness=Witness(
            client,
            load_text(DOCUMENTS_DIR / "witness_protocol_v1.md"),
            build_source_packet(),
        ),
        buddhi=Buddhi(),
        osm=OSM(),
        script=ScriptLoader(),
        ledger=KarmaLedger(tmp_path / "regen.jsonl"),
        condition=1,
        seed=1,
        episode_id="regen_ctx",
        input_hashes={},
        constitution_hash=DOCUMENT_HASHES["actor_constitution_v1.md"],
        witness_protocol_hash=DOCUMENT_HASHES["witness_protocol_v1.md"],
        script_hash=DOCUMENT_HASHES["conversation_script_v1.md"],
        source_hashes=dict(SOURCE_HASHES),
    )
    runner._run_turn(17)

    assert len(runner.last_revision_messages) == 2
    first = runner.last_revision_messages[0]
    # Structure: ... user prompt, assistant candidate, user feedback
    assert first[-3]["role"] == "user"
    assert first[-2]["role"] == "assistant"
    assert first[-1]["role"] == "user"
    assert INITIAL in first[-2]["content"]  # candidate verbatim
    assert "Please revise" in first[-1]["content"] or "UP-1" in first[-1]["content"]

    second = runner.last_revision_messages[1]
    assert REVISION_1 in second[-2]["content"]  # revises revision 1, not original
    assert INITIAL not in second[-2]["content"]

    # Intermediate revisions not in persistent history as separate commits —
    # only final output committed
    hist = runner.actor.conversation_history
    assistant_msgs = [m["content"] for m in hist if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0] == REVISION_2
    assert INITIAL not in assistant_msgs
    assert REVISION_1 not in assistant_msgs

    ev = runner.ledger.load_all()[0]
    assert ev["actor_output_initial"] == INITIAL
    assert ev["actor_output_final"] == REVISION_2
    assert ev["regeneration_count"] == 2
