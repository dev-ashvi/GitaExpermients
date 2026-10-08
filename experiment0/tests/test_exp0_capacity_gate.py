"""Boundary tests for provider-context-aware capacity hard gate (no live API)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiment1"))
sys.path.insert(0, str(REPO))

from experiment0.capacity import evaluate_capacity
from experiment0.capacity_gate import (
    CapacityConfigurationError,
    CapacityGate,
    CapacityGateError,
    CapacityGatingAnthropicClient,
    TokenCountTrust,
    UnavailableTokenCounter,
    UnverifiedEstimateCounter,
    VerifiedFixedTokenCounter,
    gate_from_provider_profile,
)


def test_capacity_1m_verified_pass():
    gate = CapacityGate(
        verified_context_limit=1_000_000,
        fraction=0.85,
        context_limit_verified=True,
        provider_profile="nvidia-nim",
    )
    # 850000 budget; 849200+800=850000 exact threshold
    r = gate.assert_request_allowed(
        prompt_tokens=849_200,
        reserved_output_tokens=800,
        token_count_trust=TokenCountTrust.VERIFIED,
        role="actor",
    )
    assert r["pass"] is True
    assert r["rhs"] == 850_000
    assert r["lhs"] == 850_000


def test_capacity_262144_provisional_arithmetic():
    """Corrected arithmetic: Actor 208676 and Witness 172014 fit 0.85*262144."""
    budget = int(262_144 * 0.85)
    assert budget == 222_822
    assert 207_876 + 800 == 208_676
    assert 208_676 <= budget
    assert 170_414 + 1600 == 172_014
    assert 172_014 <= budget

    # But DeepInfra profile is NOT verified → fail closed on gate construction use
    gate = gate_from_provider_profile("deepinfra-262k")
    with pytest.raises(CapacityConfigurationError):
        gate.budget_tokens()


def test_exact_threshold_passes():
    gate = CapacityGate(
        verified_context_limit=262_144,
        fraction=0.85,
        context_limit_verified=True,
        provider_profile="test-262k-verified",
    )
    rhs = gate.budget_tokens()
    assert rhs == 222_822
    r = gate.assert_request_allowed(
        prompt_tokens=rhs - 800,
        reserved_output_tokens=800,
        token_count_trust=TokenCountTrust.VERIFIED,
    )
    assert r["pass"] is True
    assert r["lhs"] == rhs


def test_one_token_above_threshold_fails():
    gate = CapacityGate(
        verified_context_limit=262_144,
        fraction=0.85,
        context_limit_verified=True,
        provider_profile="test-262k-verified",
    )
    rhs = gate.budget_tokens()
    with pytest.raises(CapacityGateError):
        gate.assert_request_allowed(
            prompt_tokens=rhs - 800 + 1,
            reserved_output_tokens=800,
            token_count_trust=TokenCountTrust.VERIFIED,
        )


def test_unknown_limit_fail_closed():
    gate = gate_from_provider_profile("unknown")
    with pytest.raises(CapacityConfigurationError):
        gate.budget_tokens()
    with pytest.raises(CapacityConfigurationError):
        evaluate_capacity(
            100,
            800,
            context_limit=0,
            fraction=0.85,
            context_limit_verified=False,
            provider_profile="unknown",
        )


def test_unverified_token_counts_fail_closed():
    gate = CapacityGate(
        verified_context_limit=1_000_000,
        fraction=0.85,
        context_limit_verified=True,
    )
    with pytest.raises(CapacityGateError, match="Trustworthy token count"):
        gate.assert_request_allowed(
            prompt_tokens=1000,
            reserved_output_tokens=800,
            token_count_trust=TokenCountTrust.UNVERIFIED,
        )
    with pytest.raises(CapacityGateError):
        gate.assert_request_allowed(
            prompt_tokens=None,
            reserved_output_tokens=800,
            token_count_trust=TokenCountTrust.UNAVAILABLE,
        )


def test_gating_client_uses_exact_payload_and_role_budget():
    calls = []

    class Inner:
        class messages:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs)
                from types import SimpleNamespace

                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="ok")],
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                )

    gate = CapacityGate(
        verified_context_limit=1_000_000,
        fraction=0.85,
        context_limit_verified=True,
    )
    # Counter that fails if reserved budget wrong via gate (Witness 1600)
    client = CapacityGatingAnthropicClient(
        Inner(),
        gate=gate,
        token_counter=VerifiedFixedTokenCounter(100),
        role="witness",
    )
    client.create(
        model="m",
        max_tokens=1600,
        temperature=0.0,
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert client.last_capacity_check["reserved_output"] == 1600
    assert client.last_capacity_check["prompt_tokens"] == 100
    assert len(calls) == 1
    assert calls[0]["system"] == "sys"


def test_gating_client_unavailable_counter_blocks_without_truncation():
    class Inner:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise AssertionError("must not call provider when gate fails")

    gate = CapacityGate(
        verified_context_limit=1_000_000,
        fraction=0.85,
        context_limit_verified=True,
    )
    client = CapacityGatingAnthropicClient(
        Inner(),
        gate=gate,
        token_counter=UnavailableTokenCounter(),
        role="actor",
    )
    with pytest.raises(CapacityGateError):
        client.create(
            model="m",
            max_tokens=800,
            temperature=0.7,
            system="sys",
            messages=[{"role": "user", "content": "x" * 10_000}],
        )


def test_unverified_estimate_never_authorizes():
    gate = CapacityGate(
        verified_context_limit=1_000_000,
        fraction=0.85,
        context_limit_verified=True,
    )
    client = CapacityGatingAnthropicClient(
        object(),
        gate=gate,
        token_counter=UnverifiedEstimateCounter(10),
        role="actor",
    )
    with pytest.raises(CapacityGateError, match="Trustworthy"):
        client.create(
            model="m",
            max_tokens=800,
            temperature=0.0,
            system="s",
            messages=[{"role": "user", "content": "u"}],
        )


def test_legacy_evaluate_capacity_pass_fail():
    ok = evaluate_capacity(207820, 800, context_limit=1_000_000, fraction=0.85)
    assert ok["pass"] is True
    bad = evaluate_capacity(849500, 800, context_limit=1_000_000, fraction=0.85)
    assert bad["pass"] is False
