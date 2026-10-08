"""Pre-launch operational contract tests (synthetic runs only; no live inference)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0 import engineering_config as eng
from experiment0.archival import (
    ArchivedRunError,
    assert_allowed_for_clean_analysis,
    assert_not_archived_for_resume,
    write_aborted_operational_archival_record,
)
from experiment0.capacity_gate import (
    CapacityGate,
    CapacityGateError,
    CapacityGatingAnthropicClient,
    TokenCountTrust,
    VerifiedFixedTokenCounter,
    gate_from_provider_profile,
)
from experiment0.http_pacing import FakeClock, GlobalHttpPacer
from experiment0.local_nemotron_counter import LocalNemotronChatTokenCounter
from experiment0.providers.nim_provider import NimAnthropicCompatClient
from experiment0.run_experiment import (
    build_capacity_clients,
    build_nim_http_pacer,
    episode_complete,
    run_one_episode,
)
from experiment0.tests.test_exp0_fault_recovery import (
    FakeNimProvider,
    _clients,
    _minimal_manifest,
    _slot,
)
from experiment0.tokenizer_qualification import load_qualification_evidence
from config.experiment_config import FROZEN_MANIFEST
from src.types_util import validate_input_integrity

e0 = __import__("experiment0._e0_config", fromlist=["load_experiment0_config"]).load_experiment0_config()


def test_frozen_manifest_still_14():
    verified = validate_input_integrity()
    assert len(verified) == 14
    assert set(verified.keys()) == set(FROZEN_MANIFEST.keys())


def test_scientific_defaults_unchanged():
    # Ops activation (local_hf + amendment) must not alter scientific protocol knobs.
    assert eng.PER_REQUEST_TOKEN_COUNT_MODE == "local_hf"
    assert eng.PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED is True
    assert eng.PRELAUNCH_RECOMMENDED_TOKEN_COUNT_MODE == "local_hf"
    assert eng.RETRY_AMENDMENT_V1_ENABLED is True
    assert eng.NIM_HTTP_PACING_ENABLED is True
    assert eng.NIM_HTTP_MIN_START_TO_START_SEC == 60.0
    assert eng.ACTIVE_PROVIDER_PROFILE == "nvidia-nim"
    assert eng.CONTEXT_CAPACITY_FRACTION == 0.85
    assert e0.N_EPISODES_PER_CONDITION == 30
    assert e0.TOTAL_TURNS == 25
    assert e0.MAX_TOKENS_ACTOR == 800
    assert e0.MAX_TOKENS_WITNESS == 1600
    assert e0.ACTOR_MODEL == "nvidia/nemotron-3-super-120b-a12b"


def test_tokenizer_qualification_evidence_seven_delta_zero():
    ev = load_qualification_evidence()
    assert ev is not None
    assert ev.hosted_qualification_status == "PASSED"
    assert ev.evidence_validated is True
    assert ev.provider_profile == "nvidia-nim"
    assert len(ev.probe_results) == 7
    assert all(int(p.get("delta", 1)) == 0 for p in ev.probe_results)
    assert all(p.get("status") == "PASS" for p in ev.probe_results)


def test_future_local_hf_authorizes_nvidia_rejects_unverified(monkeypatch):
    """Prepare-only: forcing local_hf mode must authorize nvidia-nim, reject deepinfra."""
    monkeypatch.setattr(eng, "PER_REQUEST_TOKEN_COUNT_MODE", "local_hf")
    provider = FakeNimProvider(mode="ok")
    # Build via real path
    inner_a = NimAnthropicCompatClient(provider, purpose="actor")
    inner_w = NimAnthropicCompatClient(provider, purpose="witness")
    actor_c, witness_c, gate = build_capacity_clients(
        provider=provider,
        actor_inner=inner_a,
        witness_inner=inner_w,
        provider_profile="nvidia-nim",
    )
    assert gate.context_limit_verified is True
    assert gate.verified_context_limit == 1_000_000
    assert isinstance(actor_c._token_counter, LocalNemotronChatTokenCounter)
    n, trust = actor_c._token_counter.count_prompt_tokens(
        "sys", [{"role": "user", "content": "ping"}]
    )
    assert trust == TokenCountTrust.VERIFIED
    assert isinstance(n, int) and n > 0

    bad_gate = gate_from_provider_profile("deepinfra-262k", fraction=0.85)
    with pytest.raises(Exception):
        bad_gate.budget_tokens()


def test_capacity_gate_qualified_local_hf_small_request():
    counter = LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim",
        model_id=e0.ACTOR_MODEL,
        enable_thinking=False,
    )
    gate = gate_from_provider_profile("nvidia-nim", fraction=0.85)
    n, trust = counter.count_prompt_tokens(
        "You are a helpful assistant.",
        [{"role": "user", "content": "Say hello in one word."}],
    )
    assert trust == TokenCountTrust.VERIFIED
    result = gate.assert_request_allowed(
        prompt_tokens=n,
        reserved_output_tokens=800,
        token_count_trust=trust,
        role="actor",
    )
    assert result["pass"] is True


def test_http_429_safe_stop_preserves_completed_and_quarantines_partial(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    run_dir = tmp_path / "synth_run_429_stop"
    (run_dir / "episodes").mkdir(parents=True)

    # Completed episode ledger (minimal fake complete turns)
    from src.karma_ledger import KarmaLedger

    done_id = "ep_done"
    done_path = run_dir / "episodes" / f"{done_id}.jsonl"
    ledger = KarmaLedger(done_path)
    for t in range(1, e0.TOTAL_TURNS + 1):
        ledger.append(
            {
                "turn": t,
                "event": "turn_complete",
                "non_scientific_marker": True,
            }
        )
    assert episode_complete(done_path)

    # Partial then 429 failure on next episode
    partial_id = "ep_partial"
    partial_path = run_dir / "episodes" / f"{partial_id}.jsonl"
    pl = KarmaLedger(partial_path)
    pl.append({"turn": 1, "event": "partial_only"})
    assert not episode_complete(partial_path)

    provider = FakeNimProvider(mode="http_429")
    actor_c, witness_c, _ = _clients(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_429_stop",
        slot=_slot(partial_id, schedule_index=1),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"
    assert episode_complete(done_path)
    # Partial should be quarantined
    bak = list((run_dir / "episodes").glob(f"{partial_id}.partial_*.jsonl.bak"))
    assert bak, "partial episode must be quarantined"
    assert not partial_path.exists() or not episode_complete(partial_path)


def test_resume_skips_completed_episodes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    run_dir = tmp_path / "synth_resume_skip"
    (run_dir / "episodes").mkdir(parents=True)
    from src.karma_ledger import KarmaLedger

    eid = "ep_complete"
    path = run_dir / "episodes" / f"{eid}.jsonl"
    ledger = KarmaLedger(path)
    for t in range(1, e0.TOTAL_TURNS + 1):
        ledger.append({"turn": t, "event": "turn_complete"})
    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, _ = _clients(provider)
    before = provider.http_attempts
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_resume",
        slot=_slot(eid),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "already_complete"
    assert provider.http_attempts == before


def test_archived_run_never_resumable():
    archived = REPO / "experiment0" / "runs" / eng.EXCLUDED_FROM_CLEAN_N60_RUN_IDS[0]
    with pytest.raises(ArchivedRunError):
        assert_not_archived_for_resume(archived)
    with pytest.raises(ArchivedRunError):
        assert_allowed_for_clean_analysis(archived)


def test_build_nim_http_pacer_and_restart(tmp_path: Path):
    clock = FakeClock(mono=0.0, wall=10_000.0)
    pacer = build_nim_http_pacer(
        runs_root=tmp_path, clock=clock, enabled=True
    )
    assert pacer is not None
    with pacer.gated_attempt(role="actor", purpose="actor") as a:
        a["http_status"] = 200
        a["ok"] = True
    state = tmp_path / eng.NIM_HTTP_PACING_OPS_DIRNAME / eng.NIM_HTTP_PACING_STATE_FILENAME
    assert state.exists()
    clock2 = FakeClock(mono=0.0, wall=10_030.0)
    pacer2 = build_nim_http_pacer(runs_root=tmp_path, clock=clock2, enabled=True)
    assert pacer2 is not None
    with pacer2.gated_attempt(role="witness", purpose="witness") as a2:
        a2["http_status"] = 200
        a2["ok"] = True
    assert abs(sum(clock2.sleeps) - 30.0) < 1e-6


def test_no_scientific_outcome_inspection_in_ops_progress(tmp_path: Path, monkeypatch):
    """Operational progress writer must not compute science metrics."""
    from experiment0.run_experiment import write_progress

    run_dir = tmp_path / "ops_only"
    run_dir.mkdir()
    write_progress(
        run_dir,
        episodes_attempted=1,
        episodes_completed=0,
        episodes_failed_operational=0,
        provider_failures=0,
        status="RUNNING",
        elapsed_sec=1.0,
        note="operational_only_no_scientific_metrics",
    )
    payload = json.loads((run_dir / "operational_progress.json").read_text(encoding="utf-8"))
    blob = json.dumps(payload)
    assert "overall_score" not in blob
    assert "verdict" not in blob
    assert "truth" not in blob
    assert payload.get("note") == "operational_only_no_scientific_metrics"


def test_nvidia_profile_1m_85_percent():
    gate = gate_from_provider_profile("nvidia-nim", fraction=eng.CONTEXT_CAPACITY_FRACTION)
    assert gate.budget_tokens() == int(1_000_000 * 0.85)
