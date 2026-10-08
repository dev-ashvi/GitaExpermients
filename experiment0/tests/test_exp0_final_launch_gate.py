"""Final NVIDIA launch-gate dry-run — mocks/temp dirs only; no live inference."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pytest

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0 import engineering_config as eng
from experiment0.archival import ArchivedRunError, assert_not_archived_for_resume
from experiment0.capacity_gate import (
    LiveProviderTokenCounter,
    TokenCountTrust,
    VerifiedFixedTokenCounter,
)
from experiment0.episode_runner import Experiment0EpisodeRunner
from experiment0.local_nemotron_counter import LocalNemotronChatTokenCounter
from experiment0.providers.nim_provider import NimAnthropicCompatClient
from experiment0.retry_amendment import (
    TerminalOperationalError,
    amendment_enabled,
    amendment_provenance,
)
from experiment0.run_experiment import (
    bind_episode_ids,
    build_capacity_clients,
    create_assignment_schedule,
    episode_complete,
    run_one_episode,
)
from experiment0.tests.test_exp0_fault_recovery import (
    FakeNimProvider,
    _clients,
    _minimal_manifest,
    _slot,
)
from experiment0.tests.test_exp0_retry_amendment_v1 import PhaseFailProvider, _clients_phase
from experiment0.tokenizer_qualification import load_qualification_evidence
from config.experiment_config import FROZEN_MANIFEST
from src.types_util import validate_input_integrity

e0 = __import__(
    "experiment0._e0_config", fromlist=["load_experiment0_config"]
).load_experiment0_config()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)


# --- Task 1 / 3: activated configuration ------------------------------------


def test_activated_ops_configuration():
    assert eng.RETRY_AMENDMENT_V1_ENABLED is True
    assert eng.PER_REQUEST_TOKEN_COUNT_MODE == "local_hf"
    assert eng.PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED is True
    assert eng.NIM_HTTP_PACING_ENABLED is True
    assert eng.NIM_HTTP_MIN_START_TO_START_SEC == 60.0
    assert eng.ACTIVE_PROVIDER_PROFILE == "nvidia-nim"
    assert amendment_enabled() is True
    prov = amendment_provenance()
    assert prov["enabled"] is True
    assert prov["physical_attempt_budgets"]["http_429"] == 1
    assert prov["physical_attempt_budgets"]["http_5xx"] == 2


def test_scientific_protocol_files_unchanged():
    verified = validate_input_integrity()
    assert len(verified) == 14
    assert set(verified) == set(FROZEN_MANIFEST)
    assert e0.ACTOR_MODEL == "nvidia/nemotron-3-super-120b-a12b"
    assert e0.WITNESS_MODEL == e0.ACTOR_MODEL
    assert e0.NIM_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert e0.TOTAL_TURNS == 25
    assert e0.N_EPISODES_PER_CONDITION == 30
    assert e0.TOTAL_EPISODES == 60
    assert e0.MAX_TOKENS_ACTOR == 800
    assert e0.MAX_TOKENS_WITNESS == 1600
    assert e0.ACTOR_TEMPERATURE == 0.7
    assert e0.WITNESS_TEMPERATURE == 0.0
    assert e0.ENABLE_THINKING is False


def test_tokenizer_and_capacity_launch_profile():
    ev = load_qualification_evidence()
    assert ev is not None
    assert ev.hosted_qualification_status == "PASSED"
    assert ev.evidence_validated is True
    assert len(ev.probe_results) == 7
    assert all(p.get("delta") == 0 for p in ev.probe_results)
    profile = eng.PROVIDER_CONTEXT_PROFILES["nvidia-nim"]
    assert profile["verified_context_limit"] == 1_000_000
    assert profile["context_limit_verified"] is True
    assert eng.CONTEXT_CAPACITY_FRACTION == 0.85
    counter = LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim",
        model_id=e0.ACTOR_MODEL,
        enable_thinking=False,
    )
    n, trust = counter.count_prompt_tokens(
        "sys", [{"role": "user", "content": "hi"}]
    )
    assert trust == TokenCountTrust.VERIFIED
    assert isinstance(n, int) and n > 0


def test_local_hf_not_live_provider_counter():
    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, gate = build_capacity_clients(
        provider=provider,
        actor_inner=NimAnthropicCompatClient(provider, purpose="actor"),
        witness_inner=NimAnthropicCompatClient(provider, purpose="witness"),
    )
    assert isinstance(actor_c._token_counter, LocalNemotronChatTokenCounter)
    assert not isinstance(actor_c._token_counter, LiveProviderTokenCounter)
    assert gate.verified_context_limit == 1_000_000


def test_archived_excluded():
    archived = REPO / "experiment0" / "runs" / eng.EXCLUDED_FROM_CLEAN_N60_RUN_IDS[0]
    with pytest.raises(ArchivedRunError):
        assert_not_archived_for_resume(archived)


# --- Task 2: terminal exception safety --------------------------------------


def test_keyboard_interrupt_not_ops_stop(tmp_path, monkeypatch):
    run_dir = tmp_path / "kbint"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, _ = _clients(provider)

    def boom(*_a, **_k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(Experiment0EpisodeRunner, "run", boom)
    with pytest.raises(KeyboardInterrupt):
        run_one_episode(
            run_dir=run_dir,
            run_id="synth_kb",
            slot=_slot("ep_kb"),
            manifest=_minimal_manifest(),
            provider=provider,
            actor_client=actor_c,
            witness_client=witness_c,
        )


def test_unexpected_baseexception_not_swallowed(tmp_path, monkeypatch):
    run_dir = tmp_path / "baseexc"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, _ = _clients(provider)

    class WeirdBase(BaseException):
        pass

    def boom(*_a, **_k):
        raise WeirdBase("not an ops stop")

    monkeypatch.setattr(Experiment0EpisodeRunner, "run", boom)
    with pytest.raises(WeirdBase):
        run_one_episode(
            run_dir=run_dir,
            run_id="synth_base",
            slot=_slot("ep_base"),
            manifest=_minimal_manifest(),
            provider=provider,
            actor_client=actor_c,
            witness_client=witness_c,
        )


def test_429_propagates_ops_stop_metadata(tmp_path):
    run_dir = tmp_path / "ops429"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="http_429")
    actor_c, witness_c, _ = _clients(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_429",
        slot=_slot("ep_429"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"
    assert result.get("operational_stop") is True
    assert result.get("failure_class") == "http_429"
    assert provider.http_attempts == 1
    # Incomplete must not look complete
    ledger = run_dir / "episodes" / "ep_429.jsonl"
    assert not episode_complete(ledger)


def test_timeout_propagates_ops_stop(tmp_path):
    run_dir = tmp_path / "opsto"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="timeout")
    actor_c, witness_c, _ = _clients(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_to",
        slot=_slot("ep_to"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"
    assert result.get("failure_class") == "ambiguous_timeout"
    assert not episode_complete(run_dir / "episodes" / "ep_to.jsonl")


def test_incomplete_ledger_not_marked_complete(tmp_path, monkeypatch):
    run_dir = tmp_path / "incomp"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, _ = _clients(provider)

    def fake_run(self):
        # Write only one turn then return as if done
        from src.karma_ledger import KarmaLedger

        led = KarmaLedger(self.ledger.path)
        led.append({"turn": 1, "event": "partial_only"})
        return self.ledger.path

    monkeypatch.setattr(Experiment0EpisodeRunner, "run", fake_run)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_incomp",
        slot=_slot("ep_incomp"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"
    assert result.get("failure_class") == "incomplete_ledger"
    assert not episode_complete(run_dir / "episodes" / "ep_incomp.jsonl")


def test_no_continuation_after_ops_stop(tmp_path):
    """After terminal 429, subsequent run_one_episode on same partial quarantines."""
    run_dir = tmp_path / "nocont"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="http_429")
    actor_c, witness_c, _ = _clients(provider)
    r1 = run_one_episode(
        run_dir=run_dir,
        run_id="synth_nc",
        slot=_slot("ep_nc"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert r1["status"] == "failed"
    # Second attempt with ok provider: prior incomplete (if any) quarantined then rerun
    provider2 = FakeNimProvider(mode="ok")
    actor_c2, witness_c2, _ = _clients(provider2)
    # Ensure any stub partial is present
    partial = run_dir / "episodes" / "ep_nc.jsonl"
    if not partial.exists():
        partial.write_text(json.dumps({"turn": 1}) + "\n", encoding="utf-8")
    r2 = run_one_episode(
        run_dir=run_dir,
        run_id="synth_nc",
        slot=_slot("ep_nc"),
        manifest=_minimal_manifest(),
        provider=provider2,
        actor_client=actor_c2,
        witness_client=witness_c2,
    )
    assert r2["status"] == "completed"
    assert list((run_dir / "episodes").glob("ep_nc.partial_*.jsonl.bak"))
    assert episode_complete(run_dir / "episodes" / "ep_nc.jsonl")


# --- Task 4: dry-run lifecycle ----------------------------------------------


def test_synthetic_schedule_generation_not_real_runs(tmp_path):
    """Disposable synthetic schedule — must not write under experiment0/runs."""
    path = tmp_path / "assignment_schedule.json"
    sched = create_assignment_schedule(path, master_seed=424242)
    assert path.exists()
    assert sched["n_total"] == 60
    assert sched["n_c1"] == 30
    assert sched["n_c2"] == 30
    assert sched["immutable"] is True
    conds = [s["condition"] for s in sched["slots"]]
    assert conds.count(1) == 30 and conds.count(2) == 30
    # Disposable path only — never write the real N=60 under experiment0/runs
    assert path.parent == tmp_path
    assert path.parent != (REPO / "experiment0" / "runs")


def test_dry_run_c1_and_c2_full_episodes(tmp_path):
    run_dir = tmp_path / "dry_c1c2"
    (run_dir / "episodes").mkdir(parents=True)
    for cond, eid in ((1, "ep_c1"), (2, "ep_c2")):
        provider = FakeNimProvider(mode="ok")
        actor_c, witness_c, _ = _clients(provider)
        result = run_one_episode(
            run_dir=run_dir,
            run_id="synth_dry",
            slot=_slot(eid, condition=cond, schedule_index=cond),
            manifest=_minimal_manifest(),
            provider=provider,
            actor_client=actor_c,
            witness_client=witness_c,
        )
        assert result["status"] == "completed"
        assert episode_complete(run_dir / "episodes" / f"{eid}.jsonl")
        # Ops-only: do not assert scientific scores
        events = [
            json.loads(line)
            for line in (run_dir / "episodes" / f"{eid}.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        assert {e["turn"] for e in events} == set(range(1, e0.TOTAL_TURNS + 1))
        assert all(e.get("condition") == cond for e in events)


def test_dry_run_resume_skip_and_bind_ids(tmp_path):
    path = tmp_path / "assignment_schedule.json"
    sched = create_assignment_schedule(path, master_seed=7)
    sched = bind_episode_ids(sched, path, run_id="synth_bind")
    ids = [s["episode_id"] for s in sched["slots"]]
    assert all(ids)
    assert len(set(ids)) == 60
    # Re-bind must not change IDs
    sched2 = bind_episode_ids(sched, path, run_id="synth_bind")
    assert [s["episode_id"] for s in sched2["slots"]] == ids

    run_dir = tmp_path / "resume_dry"
    (run_dir / "episodes").mkdir(parents=True)
    eid = ids[0]
    slot = next(s for s in sched["slots"] if s["episode_id"] == eid)
    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, _ = _clients(provider)
    r1 = run_one_episode(
        run_dir=run_dir,
        run_id="synth_bind",
        slot=slot,
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert r1["status"] == "completed"
    provider2 = FakeNimProvider(mode="ok")
    actor_c2, witness_c2, _ = _clients(provider2)
    r2 = run_one_episode(
        run_dir=run_dir,
        run_id="synth_bind",
        slot=slot,
        manifest=_minimal_manifest(),
        provider=provider2,
        actor_client=actor_c2,
        witness_client=witness_c2,
    )
    assert r2["status"] == "already_complete"
    assert provider2.http_attempts == 0


def test_dry_run_429_then_quarantine_path(tmp_path):
    run_dir = tmp_path / "dry_429"
    (run_dir / "episodes").mkdir(parents=True)
    provider = PhaseFailProvider(fail_phase="actor_raw", mode="http_429")
    actor_c, witness_c, _ = _clients_phase(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_d429",
        slot=_slot("ep_d429"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"
    assert result.get("operational_stop") is True
    # No complete ledger
    assert not episode_complete(run_dir / "episodes" / "ep_d429.jsonl")


def test_no_provider_fallback_configured():
    assert eng.ACTIVE_PROVIDER_PROFILE == "nvidia-nim"
    assert "openrouter" not in eng.PROVIDER_CONTEXT_PROFILES
    assert eng.PROVIDER_CONTEXT_PROFILES["deepinfra-262k"]["context_limit_verified"] is False
