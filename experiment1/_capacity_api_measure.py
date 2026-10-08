"""Capacity measurement only: Anthropic count_tokens on exact harness payloads.

No messages.create / generation. No frozen-file or constant mutations.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import anthropic

from config.experiment_config import (
    ACTOR_MODEL,
    CONTEXT_CAPACITY_FRACTION,
    DOCUMENTS_DIR,
    MAX_TOKENS_ACTOR,
    MODEL_CONTEXT_LIMIT,
    TOTAL_TURNS,
    WITNESS_MODEL,
)
from src.actor import build_actor_system_prompt
from src.script_loader import (
    NEUTRAL_RESPONSES,
    PRESSURE_RESPONSES,
    REWARD_RESPONSES,
    ScriptLoader,
)
from config.experiment_config import SALIENCE_TURNS
from src.types_util import build_source_packet, estimate_tokens, load_text
from src.witness import Witness


MODEL = ACTOR_MODEL  # claude-sonnet-4-6; Witness uses same id


def count_tokens(client: anthropic.Anthropic, *, system: str, messages: list[dict]) -> int:
    resp = client.messages.count_tokens(
        model=MODEL,
        system=system,
        messages=messages,
    )
    return int(resp.input_tokens)


def fill_max_output_budget() -> str:
    """Synthetic text intended to consume ~MAX_TOKENS_ACTOR under the model tokenizer.

    Used only for projected worst-case assistant/feedback bodies (no live generation).
    """
    # Dense ASCII; tokenizer typically ~1 token per ~4 chars for this pattern.
    return ("W" * 4) * MAX_TOKENS_ACTOR


def frozen_user_response_worst_case(turn: int) -> str:
    """Exact frozen stimulus string; for salience turns pick the longer of reward/pressure."""
    if turn == 25:
        return ""
    if turn in SALIENCE_TURNS:
        r = REWARD_RESPONSES[turn]
        p = PRESSURE_RESPONSES[turn]
        return r if len(r) >= len(p) else p
    return NEUTRAL_RESPONSES[turn]


def committed_history_through(script: ScriptLoader, last_completed_turn: int) -> list[dict[str, str]]:
    """Rebuild Actor conversation_history after last_completed_turn commits."""
    history: list[dict[str, str]] = []
    for t in range(1, last_completed_turn + 1):
        up = script.get_turn(t)
        ur = frozen_user_response_worst_case(t)
        history.append({"role": "user", "content": up})
        history.append({"role": "assistant", "content": fill_max_output_budget()})
        if ur:
            history.append({"role": "user", "content": ur})
    return history


def main() -> int:
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY from environment

    constitution = load_text(DOCUMENTS_DIR / "actor_constitution_v1.md")
    source_packet = build_source_packet()
    actor_system = build_actor_system_prompt(constitution, source_packet)

    # Witness system prompt via class (no API generate)
    w = Witness(
        client=None,
        protocol_text=load_text(DOCUMENTS_DIR / "witness_protocol_v1.md"),
        source_packet_text=source_packet,
    )
    witness_system = w.system_prompt

    script = ScriptLoader()
    turn1_prompt = script.get_turn(1)

    # --- Exact real payloads (no generation) ---
    # Actor Turn 1: system + first user prompt only
    actor_t1 = count_tokens(
        client,
        system=actor_system,
        messages=[{"role": "user", "content": turn1_prompt}],
    )

    # Witness single-eval request: system + SOURCE PACKET + user turn + agent output
    max_actor_out = fill_max_output_budget()
    witness_user = w.build_eval_user_message(turn1_prompt, max_actor_out)
    witness_eval = count_tokens(
        client,
        system=witness_system,
        messages=[{"role": "user", "content": witness_user}],
    )

    # Component counts (system-only via minimal user message, then subtract)
    ping = count_tokens(client, system="", messages=[{"role": "user", "content": "."}])
    actor_sys_plus_ping = count_tokens(
        client, system=actor_system, messages=[{"role": "user", "content": "."}]
    )
    witness_sys_plus_ping = count_tokens(
        client, system=witness_system, messages=[{"role": "user", "content": "."}]
    )
    sources_as_user = count_tokens(
        client,
        system="",
        messages=[{"role": "user", "content": source_packet}],
    )

    actor_system_tokens_api = actor_sys_plus_ping - ping
    witness_system_tokens_api = witness_sys_plus_ping - ping
    source_packet_tokens_api = sources_as_user - ping

    # --- Projected Actor end-of-episode / revision-worst payloads ---
    # After turns 1..24 committed: [user][assistant max][user_response] each; then turn 25 prompt.
    history24 = committed_history_through(script, 24)
    turn25_prompt = script.get_turn(25)
    actor_t25_messages = history24 + [{"role": "user", "content": turn25_prompt}]
    actor_t25 = count_tokens(client, system=actor_system, messages=actor_t25_messages)

    # Worst-case revision on turn 15 after turns 1..14 committed
    hist14 = committed_history_through(script, 14)
    t15_prompt = script.get_turn(15)
    revision_messages = hist14 + [
        {"role": "user", "content": t15_prompt},
        {"role": "assistant", "content": fill_max_output_budget()},
        {"role": "user", "content": fill_max_output_budget()},  # Buddhi feedback ≤ max_tokens budget
    ]
    actor_revision_t15 = count_tokens(client, system=actor_system, messages=revision_messages)

    # Models API documented limits for this exact endpoint id
    model_info = None
    try:
        mi = client.models.retrieve(MODEL)
        model_info = mi.model_dump() if hasattr(mi, "model_dump") else dict(mi)
    except Exception as e:  # noqa: BLE001
        model_info = {"retrieve_error": type(e).__name__, "message": str(e)[:300]}

    # Harness conservative preflight numbers (unchanged constants; for comparison only)
    harness_actor_est = (
        estimate_tokens(actor_system)
        + TOTAL_TURNS * MAX_TOKENS_ACTOR
        + TOTAL_TURNS * MAX_TOKENS_ACTOR
        + TOTAL_TURNS * 100
        + 2000
    )
    harness_witness_est = (
        estimate_tokens(witness_system)
        + estimate_tokens(source_packet)
        + MAX_TOKENS_ACTOR
        + 500
    )
    harness_limit_90 = int(MODEL_CONTEXT_LIMIT * CONTEXT_CAPACITY_FRACTION)

    report = {
        "model_id": MODEL,
        "witness_model_id": WITNESS_MODEL,
        "api_method": "client.messages.count_tokens (no messages.create)",
        "documented_context_window": {
            "anthropic_docs_context_windows": "Claude Sonnet 4.6 has a 1M-token context window (default; no beta header).",
            "source_url": "https://platform.claude.com/docs/en/build-with-claude/context-windows",
            "models_api_retrieve": model_info,
        },
        "harness_constants_unchanged": {
            "MODEL_CONTEXT_LIMIT": MODEL_CONTEXT_LIMIT,
            "CONTEXT_CAPACITY_FRACTION": CONTEXT_CAPACITY_FRACTION,
            "harness_limit_90pct": harness_limit_90,
            "MAX_TOKENS_ACTOR": MAX_TOKENS_ACTOR,
            "TOTAL_TURNS": TOTAL_TURNS,
        },
        "payload_sizes_chars": {
            "actor_system": len(actor_system),
            "witness_system": len(witness_system),
            "source_packet": len(source_packet),
            "turn1_prompt": len(turn1_prompt),
            "witness_user_eval_worst": len(witness_user),
        },
        "api_input_token_counts": {
            "actor_turn1_request": actor_t1,
            "actor_turn25_projected_max_history": actor_t25,
            "actor_turn15_revision_projected_worst": actor_revision_t15,
            "witness_eval_request_worst_actor_output": witness_eval,
            "derived_actor_system_only": actor_system_tokens_api,
            "derived_witness_system_only": witness_system_tokens_api,
            "derived_source_packet_as_user_message": source_packet_tokens_api,
            "ping_overhead_dot_user": ping,
        },
        "harness_preflight_char_estimator_comparison": {
            "actor_estimate": harness_actor_est,
            "witness_estimate": harness_witness_est,
            "limit_90pct_using_frozen_MODEL_CONTEXT_LIMIT_200k": harness_limit_90,
            "note": "Harness estimator uses ~3 chars/token and MODEL_CONTEXT_LIMIT=200000; not modified.",
        },
        "capacity_vs_documented_1M": {
            "documented_limit_tokens": 1_000_000,
            "documented_90pct": 900_000,
            "actor_turn1_pct_of_1M": round(100.0 * actor_t1 / 1_000_000, 4),
            "actor_t25_pct_of_1M": round(100.0 * actor_t25 / 1_000_000, 4),
            "actor_revision_t15_pct_of_1M": round(100.0 * actor_revision_t15 / 1_000_000, 4),
            "witness_eval_pct_of_1M": round(100.0 * witness_eval / 1_000_000, 4),
            "actor_t25_within_documented_90pct": actor_t25 <= 900_000,
            "witness_eval_within_documented_90pct": witness_eval <= 900_000,
        },
        "capacity_vs_frozen_harness_200k_constant": {
            "frozen_limit": MODEL_CONTEXT_LIMIT,
            "frozen_90pct": harness_limit_90,
            "actor_t25_within_frozen_90pct": actor_t25 <= harness_limit_90,
            "witness_eval_within_frozen_90pct": witness_eval <= harness_limit_90,
            "note": "Frozen harness constant remains 200k; Anthropic documents 1M for this model id.",
        },
    }

    out = ROOT / "CONTEXT_CAPACITY_API_REPORT.md"
    lines = [
        "# CONTEXT_CAPACITY_API_REPORT",
        "",
        "Measurement-only report. **No frozen files or capacity constants were modified.**",
        "**No** `messages.create` / generation calls. **No** pilot.",
        "",
        f"- Model endpoint counted: `{MODEL}`",
        f"- API: `messages.count_tokens` (Anthropic Python SDK)",
        "",
        "## Documented context limit (`claude-sonnet-4-6`)",
        "",
        "Per Anthropic Context windows documentation:",
        "",
        "> Claude Sonnet 4.6 … have a **1M-token** context window. … 1M is the default: you don't need a beta header.",
        "",
        f"- Source: https://platform.claude.com/docs/en/build-with-claude/context-windows",
        f"- Models API retrieve payload (raw):",
        "",
        "```json",
        json.dumps(model_info, indent=2, default=str)[:8000],
        "```",
        "",
        "## Exact real payload construction",
        "",
        "- Actor system = harness `build_actor_system_prompt(constitution, build_source_packet())`",
        "- Witness system = harness `Witness._build_system_prompt()`",
        "- Witness user = harness `build_eval_user_message(user_turn, actor_output)` with real source packet",
        "- Turn prompts + user responses from frozen `ScriptLoader` / response tables",
        "- Projected history assistant/feedback bodies filled to `MAX_TOKENS_ACTOR` budget for worst-case sizing (not live outputs)",
        "",
        "## API input token counts",
        "",
        "| payload | input_tokens |",
        "|---|---:|",
        f"| Actor Turn 1 (system + turn-1 user) | {actor_t1} |",
        f"| Actor Turn 25 projected max history | {actor_t25} |",
        f"| Actor Turn 15 revision projected worst | {actor_revision_t15} |",
        f"| Witness eval (system + sources + max actor out) | {witness_eval} |",
        f"| Derived: Actor system only | {actor_system_tokens_api} |",
        f"| Derived: Witness system only | {witness_system_tokens_api} |",
        f"| Derived: source packet as user message | {source_packet_tokens_api} |",
        "",
        "## Comparison to frozen harness preflight (unchanged)",
        "",
        f"| quantity | value |",
        f"|---|---:|",
        f"| `MODEL_CONTEXT_LIMIT` (frozen) | {MODEL_CONTEXT_LIMIT} |",
        f"| frozen 90% limit | {harness_limit_90} |",
        f"| harness actor_estimate (char heuristic) | {harness_actor_est} |",
        f"| harness witness_estimate (char heuristic) | {harness_witness_est} |",
        f"| API Actor T25 projected | {actor_t25} |",
        f"| API Witness eval worst | {witness_eval} |",
        "",
        "## Capacity verdicts (measurement only)",
        "",
        f"- Against **documented 1M** (90% = 900000): "
        f"Actor T25 {'PASS' if actor_t25 <= 900_000 else 'FAIL'}; "
        f"Witness eval {'PASS' if witness_eval <= 900_000 else 'FAIL'}",
        f"- Against **frozen harness 200k×0.9 = {harness_limit_90}**: "
        f"Actor T25 {'PASS' if actor_t25 <= harness_limit_90 else 'FAIL'}; "
        f"Witness eval {'PASS' if witness_eval <= harness_limit_90 else 'FAIL'}",
        "",
        "This report does not change readiness gates or constants.",
        "",
        "## Machine-readable dump",
        "",
        "```json",
        json.dumps(report, indent=2),
        "```",
        "",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "_capacity_api_counts.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "actor_t1": actor_t1,
        "actor_t25": actor_t25,
        "actor_revision_t15": actor_revision_t15,
        "witness_eval": witness_eval,
        "actor_system": actor_system_tokens_api,
        "source_packet": source_packet_tokens_api,
        "documented_limit": 1_000_000,
        "frozen_90pct": harness_limit_90,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except anthropic.APIError as e:
        print(json.dumps({"error": "APIError", "type": type(e).__name__, "message": str(e)[:500]}))
        raise SystemExit(2)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:500]}))
        raise SystemExit(1)
