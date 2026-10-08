"""Deterministic tests for global NIM HTTP pacing (no live inference)."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0 import engineering_config as eng
from experiment0.http_pacing import FakeClock, GlobalHttpPacer, PacingError
from experiment0.providers.base import ProviderError, ProviderRequest
from experiment0.providers.nim_provider import NimAnthropicCompatClient, NimChatProvider
from experiment0.retry_amendment import amendment_enabled, maybe_stop_on_429


def _pacer(tmp_path: Path, clock: FakeClock, **kwargs: Any) -> GlobalHttpPacer:
    return GlobalHttpPacer(
        state_path=tmp_path / "pacing_state.json",
        attempt_log_path=tmp_path / "attempts.jsonl",
        min_interval_sec=60.0,
        clock=clock,
        enabled=True,
        **kwargs,
    )


def test_pacing_enforces_60s_start_to_start(tmp_path: Path):
    clock = FakeClock(mono=1000.0, wall=1_700_000_000.0)
    pacer = _pacer(tmp_path, clock)
    with pacer.gated_attempt(role="actor", purpose="actor") as a1:
        a1["http_status"] = 200
        a1["ok"] = True
    # Immediate second attempt must sleep ~60s on fake clock
    with pacer.gated_attempt(role="witness", purpose="witness") as a2:
        a2["http_status"] = 200
        a2["ok"] = True
    assert clock.sleeps
    assert abs(sum(clock.sleeps) - 60.0) < 1e-6
    assert a2["inter_start_interval_sec"] is not None
    assert a2["inter_start_interval_sec"] >= 60.0 - 1e-6
    assert a1["role"] == "actor"
    assert a2["role"] == "witness"


def test_no_overlap_when_request_exceeds_interval(tmp_path: Path):
    clock = FakeClock(mono=0.0, wall=1_000.0)
    pacer = _pacer(tmp_path, clock)
    with pacer.gated_attempt(role="actor", purpose="actor") as a1:
        a1["http_status"] = 200
        a1["ok"] = True
        clock.advance(90.0)  # request longer than 60s
    with pacer.gated_attempt(role="witness", purpose="witness") as a2:
        a2["http_status"] = 200
        a2["ok"] = True
    # No additional wait required; interval already satisfied
    assert sum(clock.sleeps) == 90.0  # only the in-request advance
    assert a2["inter_start_interval_sec"] >= 90.0 - 1e-6


def test_process_restart_restores_wall_pacing(tmp_path: Path):
    clock1 = FakeClock(mono=10.0, wall=5_000.0)
    p1 = _pacer(tmp_path, clock1)
    with p1.gated_attempt(role="actor", purpose="actor") as a1:
        a1["http_status"] = 200
        a1["ok"] = True
    # New process: fresh monotonic, same wall clock advanced only 10s
    clock2 = FakeClock(mono=0.0, wall=5_010.0)
    p2 = _pacer(tmp_path, clock2)
    with p2.gated_attempt(role="witness", purpose="witness") as a2:
        a2["http_status"] = 200
        a2["ok"] = True
    assert abs(sum(clock2.sleeps) - 50.0) < 1e-6


def test_corrupt_state_fail_closed(tmp_path: Path):
    state = tmp_path / "pacing_state.json"
    state.write_text("{not-json", encoding="utf-8")
    clock = FakeClock()
    with pytest.raises(PacingError, match="unreadable|fail closed"):
        GlobalHttpPacer(
            state_path=state,
            attempt_log_path=tmp_path / "a.jsonl",
            min_interval_sec=60.0,
            clock=clock,
        )


def test_future_state_fail_closed(tmp_path: Path):
    state = tmp_path / "pacing_state.json"
    state.write_text(
        json.dumps({"last_attempt_start_unix": 9_999_999_999.0, "attempt_index": 1}),
        encoding="utf-8",
    )
    clock = FakeClock(wall=1_700_000_000.0)
    with pytest.raises(PacingError, match="future|fail closed"):
        GlobalHttpPacer(
            state_path=state,
            attempt_log_path=tmp_path / "a.jsonl",
            min_interval_sec=60.0,
            clock=clock,
        )


def test_concurrent_call_prevention(tmp_path: Path):
    clock = FakeClock(mono=0.0, wall=1_000.0)
    pacer = _pacer(tmp_path, clock)
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hold() -> None:
        try:
            with pacer.gated_attempt(role="actor", purpose="actor") as a:
                a["http_status"] = 200
                a["ok"] = True
                entered.set()
                release.wait(timeout=2.0)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=hold)
    t.start()
    assert entered.wait(timeout=2.0)
    # Second attempt must block until first releases (no concurrent HTTP).
    second_started = threading.Event()

    def second() -> None:
        try:
            with pacer.gated_attempt(role="witness", purpose="witness") as a:
                second_started.set()
                a["http_status"] = 200
                a["ok"] = True
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t2 = threading.Thread(target=second)
    t2.start()
    # While first holds, second must not have started the attempt body.
    assert not second_started.wait(timeout=0.2)
    release.set()
    t.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert second_started.is_set()
    assert not errors


def _ok_http_response() -> bytes:
    body = {
        "id": "chatcmpl-test",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "ok"},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
    }
    return json.dumps(body).encode("utf-8")


class _FakeResp:
    def __init__(self, data: bytes, status: int = 200):
        self._data = data
        self.status = status

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def test_nim_provider_pacing_across_actor_witness(tmp_path: Path, monkeypatch):
    clock = FakeClock(mono=0.0, wall=2_000.0)
    pacer = _pacer(tmp_path, clock)
    provider = NimChatProvider(api_key="test-key-not-real", http_pacer=pacer, max_retries=1)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResp(_ok_http_response()),
    )
    actor = NimAnthropicCompatClient(provider, purpose="actor")
    witness = NimAnthropicCompatClient(provider, purpose="witness")
    actor.create(
        model="nvidia/nemotron-3-super-120b-a12b",
        max_tokens=8,
        temperature=0.0,
        system="sys",
        messages=[{"role": "user", "content": "a"}],
    )
    witness.create(
        model="nvidia/nemotron-3-super-120b-a12b",
        max_tokens=8,
        temperature=0.0,
        system="Score each policy dimension",
        messages=[{"role": "user", "content": "w"}],
    )
    assert abs(sum(clock.sleeps) - 60.0) < 1e-6
    roles = [r["role"] for r in pacer.records]
    assert roles == ["actor", "witness"]


def test_retry_attempts_respect_pacing(tmp_path: Path, monkeypatch):
    """Amendment v1: one transient 5xx then success — both physical attempts paced."""
    clock = FakeClock(mono=0.0, wall=3_000.0)
    pacer = _pacer(tmp_path, clock)
    provider = NimChatProvider(
        api_key="test-key-not-real",
        http_pacer=pacer,
        max_retries=3,
        retry_base_delay_sec=0.0,
    )
    statuses = [500, 200]

    def fake_post(url, payload, *, role="unknown", purpose=""):
        with provider.http_pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            st = statuses.pop(0)
            attempt["http_status"] = st
            attempt["ok"] = st == 200
            if st != 200:
                attempt["error_class"] = f"http_{st}"
                return st, None, "err"
            parsed = json.loads(_ok_http_response().decode())
            return st, parsed, _ok_http_response().decode()

    monkeypatch.setattr(provider, "_post_json", fake_post)
    req = ProviderRequest(
        model="nvidia/nemotron-3-super-120b-a12b",
        system="sys",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=8,
        temperature=0.0,
        purpose="actor",
    )
    out = provider.complete(req)
    assert out.text == "ok"
    assert len(pacer.records) == 2
    # One paced gap between two starts
    assert abs(sum(clock.sleeps) - 60.0) < 1e-6


def test_retry_amendment_enabled_at_launch_gate():
    assert eng.RETRY_AMENDMENT_V1_ENABLED is True
    assert amendment_enabled() is True
    from experiment0.retry_amendment import TerminalOperationalError

    with pytest.raises(TerminalOperationalError):
        maybe_stop_on_429(429, "rate limited")


def test_retry_amendment_stops_on_429_when_enabled(monkeypatch):
    from experiment0.retry_amendment import TerminalOperationalError

    monkeypatch.setattr(eng, "RETRY_AMENDMENT_V1_ENABLED", True)
    monkeypatch.setattr(eng, "RETRY_AMENDMENT_V1_STOP_ON_HTTP_429", True)
    with pytest.raises(TerminalOperationalError) as ei:
        maybe_stop_on_429(429, "slow down")
    assert ei.value.status_code == 429
    assert ei.value.failure_class == "http_429"
    assert not isinstance(ei.value, Exception)


def test_attempt_log_has_no_message_bodies(tmp_path: Path):
    clock = FakeClock()
    pacer = _pacer(tmp_path, clock)
    with pacer.gated_attempt(role="actor", purpose="actor") as a:
        a["http_status"] = 200
        a["ok"] = True
    blob = (tmp_path / "attempts.jsonl").read_text(encoding="utf-8")
    assert "messages" not in blob
    assert "system" not in blob
    rec = json.loads(blob.strip())
    assert set(rec.keys()) >= {
        "attempt_index",
        "role",
        "purpose",
        "actual_start_utc",
        "http_status",
    }


def test_provider_identity_mismatch_still_surfaces():
    p = NimChatProvider(api_key="test-key-not-real")
    parsed = {
        "model": "someone-else/model",
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    norm = p._normalize(parsed, latency_ms=1, retries=0)
    assert norm.model_id_returned == "someone-else/model"
