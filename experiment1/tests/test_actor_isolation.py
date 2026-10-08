"""Actor isolation tests — evaluator metadata vs generic constitutional language."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import ACTOR_TASK_FRAMING, DOCUMENTS_DIR
from src.actor import (
    Actor,
    ActorIsolationError,
    build_actor_system_prompt,
    find_actor_system_prompt_violations,
    validate_actor_system_prompt,
)
from src.types_util import build_source_packet, load_text
from tests.conftest import (
    MockAnthropic,
    build_test_actor_system_prompt,
    default_responder,
)


def test_actor_system_prompt_contains_constitution_and_sources():
    # Authoritative constitution now passes isolation (Witness footer removed)
    constitution = load_text(DOCUMENTS_DIR / "actor_constitution_v1.md")
    prompt = build_actor_system_prompt(constitution, build_source_packet())
    assert "UP-1" in prompt or "Confidence must track evidence" in prompt
    assert "SOURCE S1" in prompt
    assert "SOURCE S5" in prompt
    assert "Constitutive condition" in prompt
    assert "Evaluation Principle" in prompt
    assert "witness_protocol" not in prompt.lower()


def test_blocks_witness_protocol_filename():
    assert find_actor_system_prompt_violations(
        "See witness_protocol_v1.md for details"
    )


def test_blocks_companion_document_witness_protocol():
    text = "Companion document: witness protocol (not visible to Actor)"
    found = find_actor_system_prompt_violations(text)
    assert found


def test_blocks_you_are_being_evaluated():
    assert find_actor_system_prompt_violations("You are being evaluated by a rater")


def test_blocks_explicit_experiment_condition_metadata():
    assert find_actor_system_prompt_violations("You are in Condition 3 of the study")
    assert find_actor_system_prompt_violations("experimental condition assignment")


def test_allows_constitutive_condition_alone():
    assert find_actor_system_prompt_violations(
        "**Constitutive condition — non-compensatory:** fidelity to evidence."
    ) == []


def test_allows_evaluation_principle_alone():
    assert find_actor_system_prompt_violations("## Evaluation Principle\n") == []


def test_allows_evaluate_the_evidence_alone():
    assert find_actor_system_prompt_violations(
        "Please evaluate the evidence carefully."
    ) == []


def test_authoritative_constitution_passes_full_isolation_scan():
    constitution = load_text(DOCUMENTS_DIR / "actor_constitution_v1.md")
    assert "witness_protocol" not in constitution.lower()
    assert "Companion document" not in constitution
    prompt = build_actor_system_prompt(constitution, build_source_packet())
    assert find_actor_system_prompt_violations(prompt) == []
    validate_actor_system_prompt(prompt)


def test_constitution_diff_is_footer_removal_only():
    """Audit: prior hash content differed only by Witness footer / version line."""
    constitution = load_text(DOCUMENTS_DIR / "actor_constitution_v1.md")
    assert "*Actor constitution version: 1.0.1*" in constitution
    assert "witness_protocol_v1.md" not in constitution
    assert "not visible to Actor" not in constitution
    # Substantive headings unchanged
    assert "## Evaluation Principle" in constitution
    assert "Constitutive condition" in constitution


def test_actor_context_contains_no_witness_fields():
    prompt = build_test_actor_system_prompt()
    client = MockAnthropic(default_responder)
    captured = []

    def hook(payload):
        captured.append(payload)

    actor = Actor(client, prompt, api_call_hook=hook)
    actor.generate("What does the evidence say?")
    assert captured
    messages_blob = json.dumps(captured[0])
    assert "overall_score" not in messages_blob
    assert '"verdict"' not in messages_blob
    assert "witness_raw" not in messages_blob


def test_actor_task_framing_has_no_witness_or_experiment_hypothesis():
    framing = ACTOR_TASK_FRAMING.lower()
    for term in ("witness", "verdict", "hypothesis", "osm", "buddhi", "scoring"):
        assert term not in framing


def test_actor_never_receives_witness_score_in_buddhi_feedback():
    prompt = build_test_actor_system_prompt()
    client = MockAnthropic(default_responder)
    actor = Actor(client, prompt)
    with pytest.raises(ActorIsolationError):
        actor.generate_revision(
            "revise please",
            "prior candidate",
            buddhi_feedback="Your overall_score was 1.2 and verdict: REJECT",
        )


def test_commit_turn_requires_user_response():
    client = MockAnthropic(default_responder)
    actor = Actor(client, "system")
    with pytest.raises(ValueError):
        actor.commit_turn("prompt", "output", None)  # type: ignore[arg-type]


def test_clean_fixture_passes_isolation_validation():
    validate_actor_system_prompt(build_test_actor_system_prompt())
    assert find_actor_system_prompt_violations(build_test_actor_system_prompt()) == []
