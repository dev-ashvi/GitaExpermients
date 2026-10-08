"""Experiment 0 capacity preflight using exact NIM usage.prompt_tokens."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
EXP1 = REPO_ROOT / "experiment1"
if str(EXP1) not in sys.path:
    sys.path.insert(0, str(EXP1))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiment0 import engineering_config as eng  # noqa: E402
from experiment0._e0_config import load_experiment0_config  # noqa: E402
from experiment0.capacity_gate import (  # noqa: E402
    CapacityGate,
    TokenCountTrust,
    gate_from_provider_profile,
)
from experiment0.providers.base import ProviderRequest  # noqa: E402
from experiment0.providers.nim_provider import NimChatProvider  # noqa: E402
from experiment0.script_loader import Experiment0ScriptLoader  # noqa: E402
from src.actor import build_actor_system_prompt  # noqa: E402
from src.script_loader import (  # noqa: E402
    NEUTRAL_RESPONSES,
    PRESSURE_RESPONSES,
    REWARD_RESPONSES,
)
from src.types_util import build_source_packet, load_text  # noqa: E402
from src.witness import Witness  # noqa: E402

e0 = load_experiment0_config()


def _fill_max(n: int) -> str:
    return ("W" * 4) * n


def _frozen_user_response_worst(turn: int) -> str:
    if turn == 25:
        return ""
    if turn in e0.OBSTRUCTION_SHARED_RESPONSES:
        return e0.OBSTRUCTION_SHARED_RESPONSES[turn]
    if turn in e0.SALIENCE_TURNS:
        r, p = REWARD_RESPONSES[turn], PRESSURE_RESPONSES[turn]
        return r if len(r) >= len(p) else p
    return NEUTRAL_RESPONSES[turn]


def build_actor_worst_case_request() -> ProviderRequest:
    script = Experiment0ScriptLoader()
    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    sources = build_source_packet(e0.SOURCES_DIR)
    system = build_actor_system_prompt(
        constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
    )
    history: list[dict[str, str]] = []
    for t in range(1, 25):
        up = script.get_turn(t)
        ur = _frozen_user_response_worst(t)
        history.append({"role": "user", "content": up})
        history.append({"role": "assistant", "content": _fill_max(e0.MAX_TOKENS_ACTOR)})
        if ur:
            history.append({"role": "user", "content": ur})
    history.append({"role": "user", "content": script.get_turn(25)})
    return ProviderRequest(
        model=e0.ACTOR_MODEL,
        system=system,
        messages=history,
        max_tokens=e0.MAX_TOKENS_ACTOR,
        temperature=0.0,
        enable_thinking=e0.ENABLE_THINKING,
        purpose="actor_capacity_preflight",
    )


def build_witness_worst_case_request() -> ProviderRequest:
    script = Experiment0ScriptLoader()
    sources = build_source_packet(e0.SOURCES_DIR)
    protocol = load_text(e0.DOCUMENTS_DIR / "witness_protocol_v1.md")
    w = Witness(None, protocol, sources)
    user = w.build_eval_user_message(
        script.get_turn(1), _fill_max(e0.MAX_TOKENS_ACTOR)
    )
    return ProviderRequest(
        model=e0.WITNESS_MODEL,
        system=w.system_prompt,
        messages=[{"role": "user", "content": user}],
        max_tokens=e0.MAX_TOKENS_WITNESS,
        temperature=0.0,
        enable_thinking=e0.ENABLE_THINKING,
        purpose="witness_capacity_preflight",
    )


def evaluate_capacity(
    prompt_tokens: int,
    reserved_output: int,
    *,
    context_limit: int,
    fraction: float,
    context_limit_verified: bool = True,
    provider_profile: str = "explicit",
    token_count_trust: TokenCountTrust = TokenCountTrust.VERIFIED,
) -> dict[str, Any]:
    """Arithmetic helper; raises CapacityGateError / CapacityConfigurationError on fail-closed."""
    gate = CapacityGate(
        verified_context_limit=context_limit,
        fraction=fraction,
        context_limit_verified=context_limit_verified,
        provider_profile=provider_profile,
    )
    return gate.evaluate(
        prompt_tokens=prompt_tokens,
        reserved_output_tokens=reserved_output,
        token_count_trust=token_count_trust,
    )


def run_capacity_preflight(
    provider: NimChatProvider,
    *,
    provider_profile: Optional[str] = None,
) -> dict[str, Any]:
    profile = provider_profile or eng.ACTIVE_PROVIDER_PROFILE
    gate = gate_from_provider_profile(
        profile, fraction=e0.CONTEXT_CAPACITY_FRACTION
    )
    # Fail closed before any counting if the active profile is unqualified.
    try:
        _ = gate.budget_tokens()
    except CapacityConfigurationError:
        raise

    actor_req = build_actor_worst_case_request()
    witness_req = build_witness_worst_case_request()
    actor_pt = provider.count_prompt_tokens(actor_req)
    witness_pt = provider.count_prompt_tokens(witness_req)
    actor = gate.evaluate(
        prompt_tokens=actor_pt,
        reserved_output_tokens=e0.MAX_TOKENS_ACTOR,
        token_count_trust=TokenCountTrust.VERIFIED,
    )
    witness = gate.evaluate(
        prompt_tokens=witness_pt,
        reserved_output_tokens=e0.MAX_TOKENS_WITNESS,
        token_count_trust=TokenCountTrust.VERIFIED,
    )
    return {
        "ok": bool(actor["pass"] and witness["pass"]),
        "actor": actor,
        "witness": witness,
        "provider_profile": profile,
        "diagnostic_reference": {
            "actor_prompt_tokens_nvidia_prior": 207876,
            "witness_prompt_tokens_nvidia_prior": 170414,
            "note": (
                "NVIDIA-derived prior counts only; not DeepInfra-verified. "
                "Do not treat as provider qualification for alternate backends."
            ),
        },
    }
