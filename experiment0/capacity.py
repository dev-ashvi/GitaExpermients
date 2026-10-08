"""Experiment 0 capacity preflight using exact NIM usage.prompt_tokens."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
EXP1 = REPO_ROOT / "experiment1"
if str(EXP1) not in sys.path:
    sys.path.insert(0, str(EXP1))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiment0._e0_config import load_experiment0_config  # noqa: E402
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
    prompt_tokens: int, reserved_output: int, *, context_limit: int, fraction: float
) -> dict[str, Any]:
    lhs = prompt_tokens + reserved_output
    rhs = int(context_limit * fraction)
    return {
        "prompt_tokens": prompt_tokens,
        "reserved_output": reserved_output,
        "lhs": lhs,
        "rhs": rhs,
        "pass": lhs <= rhs,
        "context_limit": context_limit,
        "fraction": fraction,
    }


def run_capacity_preflight(provider: NimChatProvider) -> dict[str, Any]:
    actor_req = build_actor_worst_case_request()
    witness_req = build_witness_worst_case_request()
    actor_pt = provider.count_prompt_tokens(actor_req)
    witness_pt = provider.count_prompt_tokens(witness_req)
    actor = evaluate_capacity(
        actor_pt,
        e0.MAX_TOKENS_ACTOR,
        context_limit=e0.MODEL_CONTEXT_LIMIT,
        fraction=e0.CONTEXT_CAPACITY_FRACTION,
    )
    witness = evaluate_capacity(
        witness_pt,
        e0.MAX_TOKENS_WITNESS,
        context_limit=e0.MODEL_CONTEXT_LIMIT,
        fraction=e0.CONTEXT_CAPACITY_FRACTION,
    )
    return {
        "ok": bool(actor["pass"] and witness["pass"]),
        "actor": actor,
        "witness": witness,
        "diagnostic_reference": {
            "actor_prompt_tokens_approx": 207820,
            "witness_prompt_tokens_approx": 170414,
            "note": "Reference from pre-implementation diagnostic; not hardcoded as answer.",
        },
    }
