"""Synthetic Experiment0EpisodeRunner e2e (C1/C2) — non-scientific temp ledgers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.capacity_gate import (
    CapacityGatingAnthropicClient,
    VerifiedFixedTokenCounter,
    gate_from_provider_profile,
)
from experiment0.episode_runner import Experiment0EpisodeRunner, UnsafeResumeError
from experiment0.script_loader import Experiment0ScriptLoader
from src.actor import Actor, build_actor_system_prompt
from src.buddhi import Buddhi
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.types_util import WitnessRecord, build_source_packet, load_text
from src.witness import Witness

# Reuse Exp1 mock infrastructure
sys.path.insert(0, str(EXP1))
from tests.conftest import (  # noqa: E402
    MockAnthropic,
    make_witness_payload,
    up1_revise_payload,
)

e0 = load_experiment0_config()

FROZEN_OBSTRUCTION = dict(e0.OBSTRUCTION_SHARED_RESPONSES)

NON_SCIENTIFIC_LABEL = "NON_SCIENTIFIC_SYNTHETIC_TEST_LEDGER"


def _accept_json() -> str:
    return json.dumps(make_witness_payload())


def _revise_json() -> str:
    return json.dumps(up1_revise_payload())


def make_responder(*, force_revision_on_obstruction: bool) -> Callable[[dict], str]:
    """Actor/Witness responder for synthetic Exp0 episodes."""

    def responder(kwargs: dict) -> str:
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        blob = " ".join(m.get("content", "") for m in messages)
        if "Score each policy dimension" in system:
            # Witness path
            if force_revision_on_obstruction and (
                "clearly supports" in blob.lower()
                or "clearly shows" in blob.lower()
                or "the evidence clearly" in blob.lower()
            ):
                return _revise_json()
            return _accept_json()
        # Actor path
        if "Please revise" in blob or "Constitutional requirement UP-1" in blob:
            return (
                "Evidence is mixed. Modest substitution benefits are moderately "
                "supported when replacing sugary drinks; certainty remains limited."
            )
        if force_revision_on_obstruction:
            return (
                "The evidence clearly supports using non-sugar sweeteners as a "
                "weight management tool across populations."
            )
        return (
            "Based on the five sources, evidence for non-sugar sweeteners and weight "
            "is mixed. Certainty should remain calibrated to each claim and population."
        )

    return responder


def _wrap_client(mock: MockAnthropic, role: str) -> CapacityGatingAnthropicClient:
    gate = gate_from_provider_profile(
        "nvidia-nim", fraction=e0.CONTEXT_CAPACITY_FRACTION
    )
    return CapacityGatingAnthropicClient(
        mock,
        gate=gate,
        token_counter=VerifiedFixedTokenCounter(1_000),
        role=role,
    )


def _build_runner(
    tmp_path: Path,
    *,
    condition: int,
    force_revision: bool,
    episode_id: str,
    run_id: str = "synth_e0_test",
) -> tuple[Experiment0EpisodeRunner, MockAnthropic, Path]:
    ledgers = tmp_path / "non_scientific_ledgers"
    ledgers.mkdir(exist_ok=True)
    (ledgers / "README_NON_SCIENTIFIC.txt").write_text(
        NON_SCIENTIFIC_LABEL + "\nNot part of any scientific dataset.\n",
        encoding="utf-8",
    )
    ledger_path = ledgers / f"{episode_id}.jsonl"

    mock = MockAnthropic(make_responder(force_revision_on_obstruction=force_revision))
    # Separate wrapped clients so Actor/Witness call hooks stay distinct
    actor_client = _wrap_client(mock, "actor")
    witness_client = _wrap_client(mock, "witness")

    sources = build_source_packet(e0.SOURCES_DIR)
    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    system_prompt = build_actor_system_prompt(
        constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
    )
    actor = Actor(
        actor_client,
        system_prompt,
        model=e0.ACTOR_MODEL,
        temperature=e0.ACTOR_TEMPERATURE,
        max_tokens=e0.MAX_TOKENS_ACTOR,
    )
    witness = Witness(
        witness_client,
        load_text(e0.DOCUMENTS_DIR / "witness_protocol_v1.md"),
        sources,
        model=e0.WITNESS_MODEL,
        temperature=e0.WITNESS_TEMPERATURE,
        max_tokens=e0.MAX_TOKENS_WITNESS,
    )
    ledger = KarmaLedger(ledger_path, create_new=True)
    runner = Experiment0EpisodeRunner(
        actor,
        witness,
        Buddhi(),
        OSM(),
        Experiment0ScriptLoader(),
        ledger,
        condition=condition,
        seed=4242,
        episode_id=episode_id,
        run_id=run_id,
        input_hashes={"synthetic": "non_scientific"},
        constitution_hash="synthetic",
        witness_protocol_hash="synthetic",
        script_hash="synthetic",
        source_hashes={"synthetic": "non_scientific"},
        schedule_index=0,
    )
    return runner, mock, ledger_path


def _assert_episode_invariants(
    events: list[dict[str, Any]], *, condition: int, expect_some_revision: bool
) -> None:
    assert len(events) == 25
    assert {e["turn"] for e in events} == set(range(1, 26))
    script = Experiment0ScriptLoader()
    by_turn = {e["turn"]: e for e in events}

    for t in range(9, 15):
        ev = by_turn[t]
        assert ev["condition"] == condition
        wr = WitnessRecord.from_dict(ev["witness_raw"])
        expected, rtype = script.get_conditional_response(
            t, condition, wr, ev["actor_output_initial"]
        )
        assert ev["user_response"] == expected
        assert ev["user_response_type"] == rtype
        if condition == 2:
            assert ev["user_response_type"] == "neutral"
        if condition == 1:
            assert ev["user_response_type"] in ("reward", "pressure")

    for t in range(15, 25):
        ev = by_turn[t]
        assert ev["user_response"] == FROZEN_OBSTRUCTION[t]
        assert ev["user_prompt"] == script.get_turn(t)
        assert ev.get("actor_output_initial")
        assert ev.get("witness_raw")
        assert ev.get("buddhi_decision") is not None
        assert ev.get("actor_output_final")
        assert ev.get("witness_final")
        assert ev.get("osm") is not None
        assert ev.get("SAL") is None
        assert ev.get("BUD") is None

    if expect_some_revision:
        assert any(e.get("regeneration_count", 0) > 0 for e in events if e["turn"] >= 15)
        assert any(e.get("output_changed") for e in events if e["turn"] >= 15)
    else:
        assert all(e.get("regeneration_count", 0) == 0 for e in events)


def test_synth_e2e_c1_with_revision(tmp_path: Path):
    runner, mock, path = _build_runner(
        tmp_path, condition=1, force_revision=True, episode_id="synth_c1_rev"
    )
    runner.run()
    events = KarmaLedger.read_file(path)
    _assert_episode_invariants(events, condition=1, expect_some_revision=True)
    assert NON_SCIENTIFIC_LABEL in (path.parent / "README_NON_SCIENTIFIC.txt").read_text(
        encoding="utf-8"
    )

    # Isolation: Witness rubric/scores must not appear in unauthorized Actor requests
    for call in mock.messages.calls:
        system = call.get("system", "")
        if "Score each policy dimension" in system:
            continue  # Witness call
        blob = system + " " + " ".join(
            m.get("content", "") for m in call.get("messages", [])
        )
        assert "Score each policy dimension" not in system
        assert "overall_score" not in blob.lower()
        assert "witness_raw" not in blob.lower()
        assert "experimental condition" not in blob.lower()
        assert '"verdict"' not in blob.lower()


def test_synth_e2e_c2_without_revision(tmp_path: Path):
    runner, mock, path = _build_runner(
        tmp_path, condition=2, force_revision=False, episode_id="synth_c2_norev"
    )
    runner.run()
    events = KarmaLedger.read_file(path)
    _assert_episode_invariants(events, condition=2, expect_some_revision=False)

    # Identical obstruction responses vs C1 frozen set
    for e in events:
        if 15 <= e["turn"] <= 24:
            assert e["user_response"] == FROZEN_OBSTRUCTION[e["turn"]]


def test_synth_c1_c2_obstruction_identity(tmp_path: Path):
    r1, _, p1 = _build_runner(
        tmp_path, condition=1, force_revision=False, episode_id="id_c1"
    )
    r1.run()
    r2, _, p2 = _build_runner(
        tmp_path, condition=2, force_revision=False, episode_id="id_c2"
    )
    r2.run()
    e1 = {e["turn"]: e for e in KarmaLedger.read_file(p1)}
    e2 = {e["turn"]: e for e in KarmaLedger.read_file(p2)}
    for t in range(15, 25):
        assert e1[t]["user_prompt"] == e2[t]["user_prompt"]
        assert e1[t]["user_response"] == e2[t]["user_response"]


def test_episode_boundary_reset_required(tmp_path: Path):
    runner, mock, _ = _build_runner(
        tmp_path, condition=1, force_revision=False, episode_id="boundary1"
    )
    runner.run()
    assert len(runner.actor.conversation_history) > 0
    # A new episode must not reuse non-empty Actor history (episode-boundary reset)
    sources = build_source_packet(e0.SOURCES_DIR)
    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    system_prompt = build_actor_system_prompt(
        constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
    )
    ledger2 = KarmaLedger(
        tmp_path / "non_scientific_ledgers" / "boundary2.jsonl", create_new=True
    )
    runner2 = Experiment0EpisodeRunner(
        runner.actor,  # deliberately reused without reset
        Witness(
            _wrap_client(mock, "witness"),
            load_text(e0.DOCUMENTS_DIR / "witness_protocol_v1.md"),
            sources,
            model=e0.WITNESS_MODEL,
            temperature=e0.WITNESS_TEMPERATURE,
            max_tokens=e0.MAX_TOKENS_WITNESS,
        ),
        Buddhi(),
        OSM(),
        Experiment0ScriptLoader(),
        ledger2,
        condition=1,
        seed=99,
        episode_id="boundary2",
        run_id="synth",
        input_hashes={"synthetic": "non_scientific"},
        constitution_hash="synthetic",
        witness_protocol_hash="synthetic",
        script_hash="synthetic",
        source_hashes={"synthetic": "non_scientific"},
        schedule_index=1,
    )
    with pytest.raises(UnsafeResumeError, match="empty Actor history"):
        runner2.run()


def test_partial_ledger_unsafe_resume(tmp_path: Path):
    runner, _, path = _build_runner(
        tmp_path, condition=1, force_revision=False, episode_id="partial_ep"
    )
    runner._run_turn(1)
    assert path.exists()
    # New runner on same partial ledger path via Experiment0EpisodeRunner
    sources = build_source_packet(e0.SOURCES_DIR)
    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    system_prompt = build_actor_system_prompt(
        constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
    )
    mock = MockAnthropic(make_responder(force_revision_on_obstruction=False))
    ledger = KarmaLedger(path, create_new=True)  # load existing partial turns
    bad = Experiment0EpisodeRunner(
        Actor(_wrap_client(mock, "actor"), system_prompt, model=e0.ACTOR_MODEL,
              temperature=e0.ACTOR_TEMPERATURE, max_tokens=e0.MAX_TOKENS_ACTOR),
        Witness(
            _wrap_client(mock, "witness"),
            load_text(e0.DOCUMENTS_DIR / "witness_protocol_v1.md"),
            sources,
            model=e0.WITNESS_MODEL,
            temperature=e0.WITNESS_TEMPERATURE,
            max_tokens=e0.MAX_TOKENS_WITNESS,
        ),
        Buddhi(),
        OSM(),
        Experiment0ScriptLoader(),
        ledger,
        condition=1,
        seed=1,
        episode_id="partial_ep",
        run_id="synth",
        input_hashes={},
        constitution_hash="x",
        witness_protocol_hash="x",
        script_hash="x",
        source_hashes={},
        schedule_index=0,
    )
    with pytest.raises(UnsafeResumeError, match="Partial episode"):
        bad.run()
