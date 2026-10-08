"""Retry amendment v1 validation — monkeypatch-enable only; defaults stay False."""

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
from experiment0.archival import ArchivedRunError, assert_not_archived_for_resume
from experiment0.capacity_gate import VerifiedFixedTokenCounter
from experiment0.http_pacing import FakeClock, GlobalHttpPacer
from experiment0.providers.base import ProviderError, ProviderRequest
from experiment0.providers.nim_provider import NimAnthropicCompatClient, NimChatProvider
from experiment0.retry_amendment import (
    TerminalOperationalError,
    amendment_enabled,
    amendment_provenance,
    maybe_stop_on_429,
)
from experiment0.run_experiment import (
    build_capacity_clients,
    episode_complete,
    run_one_episode,
)
from experiment0.tests.test_exp0_fault_recovery import (
    FakeNimProvider,
    _minimal_manifest,
    _slot,
)
from config.experiment_config import FROZEN_MANIFEST
from src.types_util import validate_input_integrity
from src.witness import WitnessParseError, parse_witness_json

e0 = __import__(
    "experiment0._e0_config", fromlist=["load_experiment0_config"]
).load_experiment0_config()


@pytest.fixture
def enable_amendment(monkeypatch):
    monkeypatch.setattr(eng, "RETRY_AMENDMENT_V1_ENABLED", True)
    monkeypatch.setattr(eng, "RETRY_AMENDMENT_V1_STOP_ON_HTTP_429", True)
    monkeypatch.setattr(eng, "RETRY_AMENDMENT_V1_HTTP_429_MAX_PHYSICAL_ATTEMPTS", 1)
    monkeypatch.setattr(eng, "RETRY_AMENDMENT_V1_HTTP_5XX_MAX_PHYSICAL_ATTEMPTS", 2)
    monkeypatch.setattr(
        eng, "RETRY_AMENDMENT_V1_AMBIGUOUS_TIMEOUT_MAX_PHYSICAL_ATTEMPTS", 1
    )
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    assert amendment_enabled() is True
    yield


def _ok_body(text: str = "ok") -> dict:
    return {
        "id": "chatcmpl-t",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": text}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
    }


def _provider_with_pacer(tmp_path: Path, clock: FakeClock) -> tuple[NimChatProvider, GlobalHttpPacer]:
    pacer = GlobalHttpPacer(
        state_path=tmp_path / "state.json",
        attempt_log_path=tmp_path / "attempts.jsonl",
        min_interval_sec=60.0,
        clock=clock,
        enabled=True,
    )
    return (
        NimChatProvider(
            api_key="test-key-not-real",
            http_pacer=pacer,
            max_retries=3,
            retry_base_delay_sec=0.0,
        ),
        pacer,
    )


def test_launch_gate_flag_enabled_by_default():
    """Final launch gate activates amendment; still NVIDIA Exp0 engineering only."""
    assert eng.RETRY_AMENDMENT_V1_ENABLED is True
    assert amendment_enabled() is True
    assert eng.PER_REQUEST_TOKEN_COUNT_MODE == "local_hf"
    assert eng.PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED is True
    assert eng.ACTIVE_PROVIDER_PROFILE == "nvidia-nim"


def test_persistent_429_exactly_one_physical_attempt(tmp_path, enable_amendment):
    clock = FakeClock()
    provider, pacer = _provider_with_pacer(tmp_path, clock)
    statuses = [429, 429, 429]

    def post(_url, _payload, *, role="unknown", purpose=""):
        with pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            st = statuses.pop(0)
            attempt["http_status"] = st
            attempt["ok"] = False
            return st, None, "rate limited"

    provider._post_json = post  # type: ignore[method-assign]
    req = ProviderRequest(
        model=e0.ACTOR_MODEL,
        system="s",
        messages=[{"role": "user", "content": "a"}],
        max_tokens=8,
        temperature=0.0,
        purpose="actor",
    )
    with pytest.raises(TerminalOperationalError) as ei:
        provider.complete(req)
    assert ei.value.failure_class == "http_429"
    assert ei.value.status_code == 429
    assert len(pacer.records) == 1
    assert not isinstance(ei.value, Exception)


def test_persistent_500_at_most_two_physical(tmp_path, enable_amendment):
    clock = FakeClock()
    provider, pacer = _provider_with_pacer(tmp_path, clock)

    def post(_url, _payload, *, role="unknown", purpose=""):
        with pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            attempt["http_status"] = 500
            attempt["ok"] = False
            return 500, None, "server error"

    provider._post_json = post  # type: ignore[method-assign]
    req = ProviderRequest(
        model=e0.ACTOR_MODEL,
        system="s",
        messages=[{"role": "user", "content": "a"}],
        max_tokens=8,
        temperature=0.0,
        purpose="actor",
    )
    with pytest.raises(TerminalOperationalError) as ei:
        provider.complete(req)
    assert ei.value.failure_class == "http_5xx_exhausted"
    assert len(pacer.records) == 2


def test_5xx_then_success_continues(tmp_path, enable_amendment):
    clock = FakeClock()
    provider, pacer = _provider_with_pacer(tmp_path, clock)
    seq = [500, 200]

    def post(_url, _payload, *, role="unknown", purpose=""):
        with pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            st = seq.pop(0)
            attempt["http_status"] = st
            attempt["ok"] = st == 200
            if st == 200:
                return st, _ok_body("recovered"), "{}"
            return st, None, "err"

    provider._post_json = post  # type: ignore[method-assign]
    req = ProviderRequest(
        model=e0.ACTOR_MODEL,
        system="s",
        messages=[{"role": "user", "content": "a"}],
        max_tokens=8,
        temperature=0.0,
        purpose="actor",
    )
    out = provider.complete(req)
    assert out.text == "recovered"
    assert len(pacer.records) == 2


def test_ambiguous_timeout_no_second_generation(tmp_path, enable_amendment):
    clock = FakeClock()
    provider, pacer = _provider_with_pacer(tmp_path, clock)
    calls = {"n": 0}

    def post(_url, _payload, *, role="unknown", purpose=""):
        calls["n"] += 1
        with pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            attempt["ok"] = False
            attempt["error_class"] = "TimeoutError"
            raise TimeoutError("The read operation timed out")

    provider._post_json = post  # type: ignore[method-assign]
    req = ProviderRequest(
        model=e0.ACTOR_MODEL,
        system="s",
        messages=[{"role": "user", "content": "a"}],
        max_tokens=8,
        temperature=0.0,
        purpose="actor",
    )
    with pytest.raises(TerminalOperationalError) as ei:
        provider.complete(req)
    assert ei.value.failure_class == "ambiguous_timeout"
    assert calls["n"] == 1


def test_actor_outer_loop_cannot_retry_terminal_429(tmp_path, enable_amendment):
    """TerminalOperationalError bypasses Actor except Exception retries."""
    clock = FakeClock()
    provider, pacer = _provider_with_pacer(tmp_path, clock)

    def post(_url, _payload, *, role="unknown", purpose=""):
        with pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            attempt["http_status"] = 429
            attempt["ok"] = False
            return 429, None, "rl"

    provider._post_json = post  # type: ignore[method-assign]
    client = NimAnthropicCompatClient(provider, purpose="actor")
    from src.actor import Actor

    actor = Actor(
        client,
        "system",
        model=e0.ACTOR_MODEL,
        temperature=0.0,
        max_tokens=16,
    )
    with pytest.raises(TerminalOperationalError):
        actor.generate("hello")
    assert len(pacer.records) == 1


def test_witness_malformed_json_keeps_frozen_retries(enable_amendment, monkeypatch):
    """Malformed JSON must remain WitnessParseError path — not http_429 terminal."""
    calls = {"n": 0}

    class _Client:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            calls["n"] += 1
            # Valid HTTP-shaped success with broken JSON body
            return type(
                "R",
                (),
                {
                    "content": [type("B", (), {"type": "text", "text": "NOT_JSON{"})()],
                    "usage": type("U", (), {"input_tokens": 1, "output_tokens": 1})(),
                },
            )()

    from src.witness import Witness

    w = Witness(
        _Client(),
        "Score each policy dimension carefully.",
        "SOURCE PACKET",
        model=e0.WITNESS_MODEL,
        temperature=0.0,
        max_tokens=100,
    )
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    with pytest.raises(WitnessParseError):
        w.evaluate("user q", "actor answer")
    assert calls["n"] == e0.API_MAX_RETRIES == 3


def test_malformed_json_not_classified_as_429():
    with pytest.raises((WitnessParseError, ValueError)):
        parse_witness_json("definitely not json")
    # Must never surface as TerminalOperationalError / http_429
    maybe_stop_on_429(200, "ok")  # no-op when amendment disabled (default)


class PhaseFailProvider:
    """Fail on a named phase of the episode turn sequence."""

    def __init__(self, *, fail_phase: str, mode: str = "http_429"):
        self.fail_phase = fail_phase
        self.mode = mode
        self.http_attempts = 0
        self.max_retries = 3
        self.retry_base_delay_sec = 0.0
        self._phase_counts = {
            "actor_raw": 0,
            "witness_raw": 0,
            "actor_revision": 0,
            "witness_final": 0,
        }
        self.witness_payload = {
            "truth": 1,
            "uncertainty": 1,
            "scope": 1,
            "tone": 1,
            "refusal": 4,
            "overall_score": 1.0,
            "verdict": "REJECT",
            "violations": ["x"],
        }

    def _norm(self, request: ProviderRequest, text: str):
        from experiment0.providers.base import NormalizedLLMResponse

        return NormalizedLLMResponse(
            text=text,
            model_id_returned=request.model,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            finish_reason="stop",
            latency_ms=1,
            retries=0,
            raw_provider_metadata={},
        )

    def complete(self, request: ProviderRequest):
        self.http_attempts += 1
        is_witness = "Score each policy dimension" in (request.system or "")
        purpose = (request.purpose or "").lower()
        # Classify phase roughly for obstruction turns (turn 9 etc.)
        if is_witness or "witness" in purpose:
            # First witness = RAW; later = FINAL after revision
            if self._phase_counts["witness_raw"] == 0:
                phase = "witness_raw"
                self._phase_counts["witness_raw"] += 1
            else:
                phase = "witness_final"
                self._phase_counts["witness_final"] += 1
        else:
            # Actor: first = RAW; after witness reject + buddhi = revision
            if self._phase_counts["actor_raw"] == 0:
                phase = "actor_raw"
                self._phase_counts["actor_raw"] += 1
            else:
                phase = "actor_revision"
                self._phase_counts["actor_revision"] += 1

        if phase == self.fail_phase:
            if self.mode == "http_429":
                raise TerminalOperationalError(
                    "simulated 429",
                    failure_class="http_429",
                    status_code=429,
                )
            if self.mode == "timeout":
                raise TerminalOperationalError(
                    "simulated timeout",
                    failure_class="ambiguous_timeout",
                )
            raise TerminalOperationalError(
                "simulated 500",
                failure_class="http_5xx_exhausted",
                status_code=500,
            )

        if is_witness:
            # REJECT on RAW to force revision path when needed
            payload = dict(self.witness_payload)
            if phase == "witness_final":
                payload["verdict"] = "ACCEPT"
                payload["overall_score"] = 4.0
            return self._norm(request, json.dumps(payload))
        return self._norm(
            request,
            "Evidence is mixed; confidence remains calibrated.",
        )

    def count_prompt_tokens(self, request: ProviderRequest) -> int:
        return 10


def _clients_phase(provider):
    inner_a = NimAnthropicCompatClient(provider, purpose="actor")
    inner_w = NimAnthropicCompatClient(provider, purpose="witness")
    return build_capacity_clients(
        provider=provider,
        actor_inner=inner_a,
        witness_inner=inner_w,
        token_counter=VerifiedFixedTokenCounter(500),
    )


@pytest.mark.parametrize(
    "fail_phase",
    ["actor_raw", "witness_raw", "actor_revision", "witness_final"],
)
def test_429_safe_stop_by_phase(tmp_path, enable_amendment, fail_phase):
    run_dir = tmp_path / f"phase_{fail_phase}"
    (run_dir / "episodes").mkdir(parents=True)
    # Use obstruction turn condition so revision/final phases are reachable.
    # Turn 1 may not be obstruction — fail actor_raw/witness_raw on turn 1;
    # for revision/final we need an obstruction turn. Episode runs turns 1..25
    # sequentially, so actor_raw fails on turn 1 always.
    provider = PhaseFailProvider(fail_phase=fail_phase, mode="http_429")
    actor_c, witness_c, _ = _clients_phase(provider)
    # Force obstruction turns to include early turns for revision/final coverage
    import experiment0.episode_runner as er

    monkey = pytest.MonkeyPatch()
    monkey.setattr(er.e0, "OBSTRUCTION_TURNS", [1])
    monkey.setattr(e0, "OBSTRUCTION_TURNS", [1])
    try:
        result = run_one_episode(
            run_dir=run_dir,
            run_id="synth_phase",
            slot=_slot("ep_phase", condition=2, schedule_index=0),
            manifest=_minimal_manifest(),
            provider=provider,
            actor_client=actor_c,
            witness_client=witness_c,
        )
    finally:
        monkey.undo()
    assert result["status"] == "failed"
    assert result.get("operational_stop") is True
    assert result.get("failure_class") == "http_429"


def test_timeout_during_generation_stops(tmp_path, enable_amendment):
    run_dir = tmp_path / "timeout_ep"
    (run_dir / "episodes").mkdir(parents=True)
    provider = PhaseFailProvider(fail_phase="actor_raw", mode="timeout")
    actor_c, witness_c, _ = _clients_phase(provider)
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


def test_completed_preserved_partial_quarantined(tmp_path, enable_amendment):
    from src.karma_ledger import KarmaLedger

    run_dir = tmp_path / "preserve"
    (run_dir / "episodes").mkdir(parents=True)
    done = run_dir / "episodes" / "ep_done.jsonl"
    led = KarmaLedger(done)
    for t in range(1, e0.TOTAL_TURNS + 1):
        led.append({"turn": t, "event": "turn_complete"})
    assert episode_complete(done)

    partial = run_dir / "episodes" / "ep_part.jsonl"
    KarmaLedger(partial).append({"turn": 1, "event": "partial"})
    provider = PhaseFailProvider(fail_phase="actor_raw", mode="http_429")
    actor_c, witness_c, _ = _clients_phase(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_p",
        slot=_slot("ep_part"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"
    assert episode_complete(done)
    assert list((run_dir / "episodes").glob("ep_part.partial_*.jsonl.bak"))


def test_resume_no_duplicate_completed(tmp_path, enable_amendment):
    from src.karma_ledger import KarmaLedger

    run_dir = tmp_path / "nodup"
    (run_dir / "episodes").mkdir(parents=True)
    eid = "ep_ok"
    led = KarmaLedger(run_dir / "episodes" / f"{eid}.jsonl")
    for t in range(1, e0.TOTAL_TURNS + 1):
        led.append({"turn": t, "event": "turn_complete"})
    provider = PhaseFailProvider(fail_phase="actor_raw", mode="http_429")
    actor_c, witness_c, _ = _clients_phase(provider)
    before = provider.http_attempts
    r = run_one_episode(
        run_dir=run_dir,
        run_id="synth_r",
        slot=_slot(eid),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert r["status"] == "already_complete"
    assert provider.http_attempts == before


def test_archived_still_blocked(enable_amendment):
    archived = REPO / "experiment0" / "runs" / eng.EXCLUDED_FROM_CLEAN_N60_RUN_IDS[0]
    with pytest.raises(ArchivedRunError):
        assert_not_archived_for_resume(archived)


def test_schedule_condition_immutable_on_fail(tmp_path, enable_amendment):
    run_dir = tmp_path / "imm"
    (run_dir / "episodes").mkdir(parents=True)
    slot = _slot("ep_c2", condition=2, schedule_index=7)
    before = dict(slot)
    provider = PhaseFailProvider(fail_phase="actor_raw", mode="http_429")
    actor_c, witness_c, _ = _clients_phase(provider)
    run_one_episode(
        run_dir=run_dir,
        run_id="synth_imm",
        slot=slot,
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert slot == before


def test_scientific_integrity_unchanged(enable_amendment):
    verified = validate_input_integrity()
    assert len(verified) == 14
    assert set(verified) == set(FROZEN_MANIFEST)
    assert e0.TOTAL_TURNS == 25
    assert e0.N_EPISODES_PER_CONDITION == 30
    assert e0.MAX_TOKENS_ACTOR == 800
    assert e0.MAX_TOKENS_WITNESS == 1600
    assert eng.PER_REQUEST_TOKEN_COUNT_MODE == "local_hf"


def test_provenance_block_shape():
    block = amendment_provenance()
    assert block["amendment_id"] == "retry_amendment_v1"
    assert block["amendment_version"] == "1"
    assert block["enabled"] is True
    assert block["physical_attempt_budgets"]["http_429"] == 1
    assert block["physical_attempt_budgets"]["http_5xx"] == 2
    assert block["global_pacing"]["min_start_to_start_sec"] == 60.0


def test_all_physical_attempts_use_pacer(tmp_path, enable_amendment):
    clock = FakeClock()
    provider, pacer = _provider_with_pacer(tmp_path, clock)
    seq = [500, 500]

    def post(_url, _payload, *, role="unknown", purpose=""):
        with pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            st = seq.pop(0)
            attempt["http_status"] = st
            attempt["ok"] = False
            return st, None, "err"

    provider._post_json = post  # type: ignore[method-assign]
    with pytest.raises(TerminalOperationalError):
        provider.complete(
            ProviderRequest(
                model=e0.ACTOR_MODEL,
                system="s",
                messages=[{"role": "user", "content": "a"}],
                max_tokens=8,
                temperature=0.0,
                purpose="actor",
            )
        )
    assert len(pacer.records) == 2
    assert abs(sum(clock.sleeps) - 60.0) < 1e-6


def test_no_urllib_hidden_retries():
    import inspect
    import urllib.request

    src = inspect.getsource(NimChatProvider._post_json)
    assert "urlopen" in src
    assert "Retry" not in src
    assert "HTTPAdapter" not in src
