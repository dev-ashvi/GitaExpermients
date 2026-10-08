"""Fault injection + recovery on the actual Experiment 0 orchestration path."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pytest

# BaseException is builtin; used in FakeNimProvider amendment path annotations.

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.archival import (
    ArchivedRunError,
    assert_allowed_for_clean_analysis,
    assert_not_archived_for_resume,
    write_aborted_operational_archival_record,
)
from experiment0.capacity_gate import VerifiedFixedTokenCounter
from experiment0.providers.base import ProviderError, ProviderRequest
from experiment0.providers.nim_provider import NimAnthropicCompatClient
from experiment0.run_experiment import (
    build_capacity_clients,
    episode_complete,
    run_one_episode,
)
from experiment0.analyze import main as analyze_main
from src.types_util import validate_input_integrity

e0 = load_experiment0_config()


class FakeNimProvider:
    """Minimal NimChatProvider stand-in with countable HTTP attempts."""

    def __init__(
        self,
        *,
        mode: str = "ok",
        fail_times: int = 0,
        actor_text: str = (
            "Evidence for non-sugar sweeteners and weight is mixed; "
            "certainty should remain calibrated."
        ),
        witness_payload: Optional[dict] = None,
        truncate_witness: bool = False,
    ):
        self.mode = mode
        self.fail_times = fail_times
        self.failures_remaining = fail_times
        self.actor_text = actor_text
        self.witness_payload = witness_payload or {
            "truth": 3,
            "uncertainty": 3,
            "scope": 3,
            "tone": 3,
            "refusal": 4,
            "overall_score": 3.2,
            "verdict": "ACCEPT",
            "violations": [],
        }
        self.truncate_witness = truncate_witness
        self.http_attempts = 0
        self.max_retries = e0.API_MAX_RETRIES
        self.retry_base_delay_sec = 0.0  # tests patch sleep anyway
        self.complete_calls = 0

    def _one_http(self, request: ProviderRequest) -> Any:
        """Single underlying HTTP attempt (counted). Mirrors NimChatProvider attempt body."""
        from experiment0.providers.base import NormalizedLLMResponse
        from experiment0.retry_amendment import (
            TerminalOperationalError,
            amendment_enabled,
        )

        self.http_attempts += 1
        if self.mode == "timeout":
            if amendment_enabled():
                raise TerminalOperationalError(
                    "simulated timeout",
                    failure_class="ambiguous_timeout",
                )
            raise ProviderError("simulated timeout", retriable=True)
        if self.mode == "http_500":
            raise ProviderError("Transient NIM HTTP 500", status_code=500, retriable=True)
        if self.mode == "http_429":
            if amendment_enabled():
                raise TerminalOperationalError(
                    "simulated 429",
                    failure_class="http_429",
                    status_code=429,
                )
            raise ProviderError("Transient NIM HTTP 429", status_code=429, retriable=True)
        if self.mode == "fail_n_then_ok":
            if self.failures_remaining > 0:
                self.failures_remaining -= 1
                if amendment_enabled():
                    raise TerminalOperationalError(
                        "simulated 429",
                        failure_class="http_429",
                        status_code=429,
                    )
                raise ProviderError(
                    "Transient NIM HTTP 429", status_code=429, retriable=True
                )

        is_witness = "Score each policy dimension" in (request.system or "")
        if is_witness:
            text = json.dumps(self.witness_payload)
            if self.truncate_witness:
                text = text[:40]
        else:
            text = self.actor_text
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

    def complete(self, request: ProviderRequest) -> Any:
        """Mirror NimChatProvider.complete — amendment-aware when flag enabled."""
        from experiment0.retry_amendment import TerminalOperationalError, amendment_enabled

        self.complete_calls += 1
        if amendment_enabled():
            # Physical budgets: 429/timeout → 1 attempt; 5xx → up to 2.
            budget = 2 if self.mode == "http_500" else 1
            last_err: Optional[BaseException] = None
            for attempt in range(budget):
                try:
                    return self._one_http(request)
                except TerminalOperationalError:
                    raise
                except ProviderError as e:
                    last_err = e
                    if (
                        e.status_code is not None
                        and e.status_code >= 500
                        and attempt + 1 < budget
                    ):
                        time.sleep(self.retry_base_delay_sec * (2**attempt))
                        continue
                    if e.status_code is not None and e.status_code >= 500:
                        raise TerminalOperationalError(
                            str(e),
                            failure_class="http_5xx_exhausted",
                            status_code=e.status_code,
                        ) from e
                    raise
            raise ProviderError(f"NIM request failed: {last_err}", retriable=False)

        last_err_e: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                return self._one_http(request)
            except ProviderError as e:
                last_err_e = e
                if e.retriable and attempt + 1 < self.max_retries:
                    time.sleep(self.retry_base_delay_sec * (2**attempt))
                    continue
                raise
            except Exception as e:  # noqa: BLE001
                last_err_e = e
                if attempt + 1 < self.max_retries:
                    time.sleep(self.retry_base_delay_sec * (2**attempt))
                    continue
                raise ProviderError(
                    f"NIM request failed after retries: {e}", retriable=False
                ) from e
        raise ProviderError(f"NIM request failed: {last_err_e}", retriable=False)

    def count_prompt_tokens(self, request: ProviderRequest) -> int:
        return 10


def _minimal_manifest() -> dict[str, Any]:
    hashes = validate_input_integrity()
    return {
        "input_hashes": hashes,
        "constitution_hash": "synth",
        "witness_protocol_hash": "synth",
        "script_hash": "synth",
        "source_hashes": {
            k: v for k, v in hashes.items() if k.startswith("S") and k.endswith(".txt")
        },
    }


def _slot(episode_id: str, condition: int = 1, schedule_index: int = 0) -> dict:
    return {
        "condition": condition,
        "seed": 11111,
        "schedule_index": schedule_index,
        "episode_id": episode_id,
        "slot_within_condition": 0,
    }


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)


def _clients(provider: FakeNimProvider):
    inner_a = NimAnthropicCompatClient(provider, enable_thinking=False)
    inner_w = NimAnthropicCompatClient(provider, enable_thinking=False)
    return build_capacity_clients(
        provider=provider,
        actor_inner=inner_a,
        witness_inner=inner_w,
        token_counter=VerifiedFixedTokenCounter(500),
    )


def test_http_429_exhaustion_fails_episode(tmp_path: Path):
    run_dir = tmp_path / "non_scientific_run_429"
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
    assert "429" in result["error"] or "failed after retries" in result["error"].lower()


def test_http_500_exhaustion(tmp_path: Path):
    run_dir = tmp_path / "non_scientific_run_500"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="http_500")
    actor_c, witness_c, _ = _clients(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_500",
        slot=_slot("ep_500"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"


def test_timeout_exhaustion(tmp_path: Path):
    run_dir = tmp_path / "non_scientific_run_timeout"
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


def test_malformed_witness_json(tmp_path: Path):
    run_dir = tmp_path / "non_scientific_run_badjson"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="ok", truncate_witness=True)
    actor_c, witness_c, _ = _clients(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_badjson",
        slot=_slot("ep_badjson"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"


def test_retry_amplification_max_underlying_attempts(tmp_path: Path):
    """Measure nested retries: Actor outer × provider inner (frozen counts unchanged).

    Actor._call_api: API_MAX_RETRIES attempts (from Exp1 config, value 3).
    Each attempt → NimChatProvider.complete with max_retries=3.
    Max underlying complete() calls for one Actor.generate under persistent 429: 3×3=9.

    Witness.evaluate: outer API_MAX_RETRIES for exceptions × provider max_retries
    similarly up to 9 for the first Witness call if Actor somehow succeeded —
    here Actor fails first, so we measure Actor-only amplification.
    """
    run_dir = tmp_path / "non_scientific_amplification"
    (run_dir / "episodes").mkdir(parents=True)
    provider = FakeNimProvider(mode="http_429")
    # Use raw NimAnthropicCompatClient WITHOUT replacing provider max_retries
    assert provider.max_retries == e0.API_MAX_RETRIES == 3
    actor_c, witness_c, _ = _clients(provider)
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_amp",
        slot=_slot("ep_amp"),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "failed"
    from experiment0.retry_amendment import amendment_enabled

    if amendment_enabled():
        # Amendment v1: exactly one physical HTTP attempt on persistent 429.
        assert provider.http_attempts == 1, (
            f"Amendment v1 expects 1 physical 429 attempt, got {provider.http_attempts}."
        )
        assert result.get("operational_stop") is True or "429" in result.get(
            "error", ""
        ) or "http_429" in str(result.get("failure_class", ""))
    else:
        # Frozen path: Actor outer × provider inner = 9
        assert provider.http_attempts == 9, (
            f"Expected max nested amplification 9, got {provider.http_attempts}. "
            "Do not silently change frozen retry counts; report as infrastructure amendment."
        )


def test_partial_quarantine_and_resume_skip(tmp_path: Path):
    run_dir = tmp_path / "non_scientific_quarantine"
    ep_dir = run_dir / "episodes"
    ep_dir.mkdir(parents=True)
    eid = "ep_partial"
    partial = ep_dir / f"{eid}.jsonl"
    # Write incomplete ledger (1 turn stub — non-scientific)
    partial.write_text(
        json.dumps(
            {
                "turn": 1,
                "episode_id": eid,
                "note": "NON_SCIENTIFIC_SYNTHETIC_PARTIAL",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert not episode_complete(partial)

    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, _ = _clients(provider)
    # First call quarantines partial then runs full episode
    result = run_one_episode(
        run_dir=run_dir,
        run_id="synth_q",
        slot=_slot(eid),
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert result["status"] == "completed"
    baks = list(ep_dir.glob("*.partial_*.jsonl.bak"))
    assert len(baks) == 1
    assert episode_complete(ep_dir / f"{eid}.jsonl")

    # Resume: completed episode skipped without duplication
    provider2 = FakeNimProvider(mode="ok")
    actor_c2, witness_c2, _ = _clients(provider2)
    result2 = run_one_episode(
        run_dir=run_dir,
        run_id="synth_q",
        slot=_slot(eid),
        manifest=_minimal_manifest(),
        provider=provider2,
        actor_client=actor_c2,
        witness_client=witness_c2,
    )
    assert result2["status"] == "already_complete"
    assert provider2.http_attempts == 0


def test_schedule_immutability_no_condition_reassignment(tmp_path: Path):
    """Immutable schedule slots keep condition/seed across quarantine restart."""
    run_dir = tmp_path / "non_scientific_sched"
    (run_dir / "episodes").mkdir(parents=True)
    schedule = {
        "immutable": True,
        "slots": [
            _slot("ep_c1", condition=1, schedule_index=0),
            _slot("ep_c2", condition=2, schedule_index=1),
        ],
    }
    # Simulate interruption: partial on C2
    (run_dir / "episodes" / "ep_c2.jsonl").write_text(
        json.dumps({"turn": 1, "condition": 2}) + "\n", encoding="utf-8"
    )
    before = json.loads(json.dumps(schedule))
    provider = FakeNimProvider(mode="ok")
    actor_c, witness_c, _ = _clients(provider)
    run_one_episode(
        run_dir=run_dir,
        run_id="synth_sched",
        slot=schedule["slots"][1],
        manifest=_minimal_manifest(),
        provider=provider,
        actor_client=actor_c,
        witness_client=witness_c,
    )
    assert schedule["slots"][0]["condition"] == before["slots"][0]["condition"]
    assert schedule["slots"][1]["condition"] == 2
    assert schedule["slots"][1]["seed"] == before["slots"][1]["seed"]


def test_archival_blocks_resume_and_analysis(tmp_path: Path):
    run_dir = tmp_path / "e0_archived_synthetic"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "e0_archived_synthetic", "status": "STOPPED_FOR_REVIEW"}),
        encoding="utf-8",
    )
    write_aborted_operational_archival_record(
        run_dir,
        run_id="e0_archived_synthetic",
        completed_episodes=1,
        total_episodes=60,
        prior_status="STOPPED_FOR_REVIEW",
        stop_reason_ops="synthetic archival test",
    )
    with pytest.raises(ArchivedRunError):
        assert_not_archived_for_resume(run_dir)
    with pytest.raises(ArchivedRunError):
        assert_allowed_for_clean_analysis(run_dir)


def test_real_aborted_run_excluded_from_analysis():
    """Fail-closed guard for e0_20261007T132027Z without inspecting scientific text."""
    run_dir = e0.RUNS_DIR / "e0_20261007T132027Z"
    assert run_dir.exists()
    with pytest.raises(ArchivedRunError):
        assert_not_archived_for_resume(run_dir)
    with pytest.raises(ArchivedRunError):
        assert_allowed_for_clean_analysis(run_dir)
    # analyze CLI must refuse without producing scientific analysis
    rc = analyze_main(["--run-id", "e0_20261007T132027Z"])
    assert rc == 3


def test_incomplete_run_not_accidentally_analyzed_via_guard(tmp_path: Path):
    """Incomplete synthetic run with archival exclusion cannot be clean-analyzed."""
    run_id = "e0_incomplete_synth_block"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"status": "STOPPED_FOR_REVIEW", "run_id": run_id}),
        encoding="utf-8",
    )
    write_aborted_operational_archival_record(
        run_dir,
        run_id=run_id,
        completed_episodes=0,
        total_episodes=60,
        prior_status="STOPPED_FOR_REVIEW",
        stop_reason_ops="synthetic incomplete",
    )
    with pytest.raises(ArchivedRunError):
        assert_allowed_for_clean_analysis(run_dir)
