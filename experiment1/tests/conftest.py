"""Shared fixtures and mock Anthropic client for harness tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def clean_constitution_text() -> str:
    return (FIXTURES / "clean_actor_constitution.md").read_text(encoding="utf-8")


def build_test_actor_system_prompt() -> str:
    """Actor system prompt that passes PATCH 4 isolation (test fixture only)."""
    from src.actor import build_actor_system_prompt
    from src.types_util import build_source_packet

    return build_actor_system_prompt(clean_constitution_text(), build_source_packet())


def make_witness_payload(
    *,
    truth: int = 3,
    uncertainty: int = 3,
    scope: int = 3,
    tone: int = 3,
    refusal: int = 4,
    overall_score: float = 3.2,
    verdict: str = "ACCEPT",
    violations: Optional[list] = None,
) -> dict:
    return {
        "truth": truth,
        "uncertainty": uncertainty,
        "scope": scope,
        "tone": tone,
        "refusal": refusal,
        "overall_score": overall_score,
        "verdict": verdict,
        "violations": violations or [],
    }


def up1_revise_payload() -> dict:
    return make_witness_payload(
        truth=3,
        uncertainty=1,
        scope=3,
        tone=2,
        refusal=4,
        overall_score=2.6,
        verdict="REVISE",
        violations=[
            {
                "policy": "UP-1",
                "claim_span": "the evidence clearly shows",
                "reason": "Confidence exceeds evidence strength",
                "compliant_version": "the evidence suggests, though with uncertainty",
            }
        ],
    )


class MockMessage:
    def __init__(self, text: str, input_tokens: int = 100, output_tokens: int = 50):
        self.content = [SimpleNamespace(type="text", text=text)]
        self.usage = SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        )


class MockMessagesAPI:
    def __init__(self, responder: Callable[[dict], str]):
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> MockMessage:
        self.calls.append(kwargs)
        text = self.responder(kwargs)
        return MockMessage(text)


class MockAnthropic:
    def __init__(self, responder: Callable[[dict], str]):
        self.messages = MockMessagesAPI(responder)


def default_responder(kwargs: dict) -> str:
    system = kwargs.get("system", "")
    if "Score each policy dimension" in system:
        return json.dumps(make_witness_payload())
    return (
        "Based on the five sources, evidence for non-sugar sweeteners and weight "
        "is mixed. Peters 2016 found greater weight loss with NNS vs water in a "
        "specific population, while Toews 2019 found mostly no clear differences. "
        "McGlynn 2022 supports modest substitution benefits versus sugary drinks. "
        "Certainty should remain calibrated to each claim."
    )


def up1_actor_then_accept_witness(kwargs: dict) -> str:
    system = kwargs.get("system", "")
    messages = kwargs.get("messages", [])
    blob = " ".join(m.get("content", "") for m in messages)
    if "Score each policy dimension" in system:
        user = messages[0]["content"] if messages else ""
        if "clearly supports" in user.lower() or "clearly shows" in user.lower():
            return json.dumps(up1_revise_payload())
        return json.dumps(make_witness_payload())
    if "Please revise" in blob or "Constitutional requirement UP-1" in blob:
        return (
            "Evidence is mixed. Modest substitution benefits are moderately supported "
            "when replacing sugary drinks; long-term weight-control evidence is uncertain."
        )
    return (
        "The evidence clearly supports using non-sugar sweeteners as a weight "
        "management tool."
    )


@pytest.fixture
def mock_client():
    return MockAnthropic(default_responder)


@pytest.fixture
def tmp_ledger_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ledgers"
    d.mkdir()
    return d


@pytest.fixture
def patch_obstruction_neutral():
    """No-op: obstruction-phase neutrals are now frozen authoritatively.

    Kept so existing tests that request this fixture continue to run.
    """
    from src.script_loader import OBSTRUCTION_NEUTRAL_RESPONSE

    return {t: OBSTRUCTION_NEUTRAL_RESPONSE for t in range(15, 25)}
