#!/usr/bin/env python3
"""Build Stage-B qualification probe fixtures (offline only — no API calls).

Writes provider-facing request bodies + local UNVERIFIED token counts so Stage B
can compare the exact same serialization against usage.prompt_tokens.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.capacity import (
    build_actor_worst_case_request,
    build_witness_worst_case_request,
)
from experiment0.local_nemotron_counter import LocalNemotronChatTokenCounter
from experiment0.providers.message_assembly import openai_chat_request_body
from experiment0.script_loader import Experiment0ScriptLoader
from experiment0.tokenizer_qualification import write_pending_evidence_stub
from src.actor import build_actor_system_prompt
from src.types_util import build_source_packet, load_text
from src.witness import Witness

e0 = load_experiment0_config()
OUT_DIR = Path(__file__).resolve().parent


def _body_hash(body: dict[str, Any]) -> str:
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _record(
    *,
    fixture_id: str,
    role: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    counter: LocalNemotronChatTokenCounter,
    notes: str,
) -> dict[str, Any]:
    body = openai_chat_request_body(
        model=e0.ACTOR_MODEL,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        enable_thinking=False,
    )
    n, trust = counter.count_prompt_tokens(system, messages)
    return {
        "fixture_id": fixture_id,
        "role": role,
        "notes": notes,
        "non_scientific": True,
        "expected_provider_profile": "nvidia-nim",
        "model_id": e0.ACTOR_MODEL,
        "output_budget_max_tokens": max_tokens,
        "temperature": temperature,
        "enable_thinking": False,
        "add_generation_prompt": True,
        "message_shape": {
            "has_system": bool(system),
            "n_messages": len(body["messages"]),
            "roles": [m["role"] for m in body["messages"]],
        },
        "provider_facing_request_body": body,
        "provider_facing_request_body_sha256": _body_hash(body),
        "local_prompt_tokens": n,
        "local_token_trust": trust.value,
        "tokenizer_revision": counter._pinning.get("huggingface_revision"),
        "chat_template_sha256": counter.chat_template_sha256,
        "stage_b_compare_field": "usage.prompt_tokens",
        "stage_b_required_delta": 0,
    }


def main() -> None:
    counter = LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim",
        load_evidence=False,
    )
    sources = build_source_packet(e0.SOURCES_DIR)
    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    actor_system = build_actor_system_prompt(
        constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
    )
    script = Experiment0ScriptLoader()
    protocol = load_text(e0.DOCUMENTS_DIR / "witness_protocol_v1.md")
    witness = Witness(None, protocol, sources)

    fixtures: list[dict[str, Any]] = []

    # Short Actor (T1)
    fixtures.append(
        _record(
            fixture_id="short_actor_t1",
            role="actor",
            system=actor_system,
            messages=[{"role": "user", "content": script.get_turn(1)}],
            max_tokens=e0.MAX_TOKENS_ACTOR,
            temperature=e0.ACTOR_TEMPERATURE,
            counter=counter,
            notes="Minimal Actor RAW at turn 1",
        )
    )

    # Short Witness
    w_user = witness.build_eval_user_message(
        script.get_turn(1),
        "Evidence is mixed; certainty should remain calibrated.",
    )
    fixtures.append(
        _record(
            fixture_id="short_witness",
            role="witness",
            system=witness.system_prompt,
            messages=[{"role": "user", "content": w_user}],
            max_tokens=e0.MAX_TOKENS_WITNESS,
            temperature=e0.WITNESS_TEMPERATURE,
            counter=counter,
            notes="Single-turn Witness eval with short agent output",
        )
    )

    # Multi-message Actor (synthetic 3 committed turns + current)
    hist: list[dict[str, str]] = []
    for t in range(1, 4):
        hist.append({"role": "user", "content": script.get_turn(t)})
        hist.append(
            {
                "role": "assistant",
                "content": f"Synthetic non-scientific assistant reply for turn {t}.",
            }
        )
        ur, _ = script.get_conditional_response(t, 2, None)
        if ur:
            hist.append({"role": "user", "content": ur})
    hist.append({"role": "user", "content": script.get_turn(4)})
    fixtures.append(
        _record(
            fixture_id="multi_message_actor",
            role="actor",
            system=actor_system,
            messages=hist,
            max_tokens=e0.MAX_TOKENS_ACTOR,
            temperature=e0.ACTOR_TEMPERATURE,
            counter=counter,
            notes="Synthetic multi-turn Actor history (non-scientific fills)",
        )
    )

    # Revision-shaped Actor
    rev_msgs = list(hist[:-1])  # up through turn-3 user response
    rev_msgs.append({"role": "user", "content": script.get_turn(15)})
    rev_msgs.append(
        {
            "role": "assistant",
            "content": "The evidence clearly supports a strong claim (synthetic).",
        }
    )
    rev_msgs.append(
        {
            "role": "user",
            "content": (
                "Please revise: Constitutional requirement UP-1 — express "
                "confidence calibrated to evidence strength. (synthetic feedback)"
            ),
        }
    )
    fixtures.append(
        _record(
            fixture_id="revision_shaped_actor",
            role="actor",
            system=actor_system,
            messages=rev_msgs,
            max_tokens=e0.MAX_TOKENS_ACTOR,
            temperature=e0.ACTOR_TEMPERATURE,
            counter=counter,
            notes="Actor revision temporary context shape",
        )
    )

    # Worst-case Actor / Witness from capacity builders
    actor_wc = build_actor_worst_case_request()
    fixtures.append(
        _record(
            fixture_id="worst_case_actor",
            role="actor",
            system=actor_wc.system,
            messages=list(actor_wc.messages),
            max_tokens=actor_wc.max_tokens,
            temperature=actor_wc.temperature,
            counter=counter,
            notes="Capacity preflight Actor worst-case envelope",
        )
    )
    witness_wc = build_witness_worst_case_request()
    fixtures.append(
        _record(
            fixture_id="worst_case_witness",
            role="witness",
            system=witness_wc.system,
            messages=list(witness_wc.messages),
            max_tokens=witness_wc.max_tokens,
            temperature=witness_wc.temperature,
            counter=counter,
            notes="Capacity preflight Witness worst-case envelope",
        )
    )

    index = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "stage": "A_OFFLINE_ONLY",
        "hosted_probes_executed": False,
        "local_trust": "unverified",
        "fixtures": [
            {
                "fixture_id": f["fixture_id"],
                "local_prompt_tokens": f["local_prompt_tokens"],
                "body_sha256": f["provider_facing_request_body_sha256"],
                "output_budget_max_tokens": f["output_budget_max_tokens"],
            }
            for f in fixtures
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in fixtures:
        path = OUT_DIR / f"{f['fixture_id']}.json"
        path.write_text(json.dumps(f, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "INDEX.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )
    write_pending_evidence_stub()
    print(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
