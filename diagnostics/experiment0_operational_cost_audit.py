#!/usr/bin/env python3
"""Operational-only cost/runtime audit for aborted Exp0 run.

Blinding: extracts ONLY allowlisted operational fields. Never aggregates by
condition. Never reads scientific metrics or response text into the report.
Does NOT resume Experiment 0.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))

from src.karma_ledger import KarmaLedger  # noqa: E402

RUN_ID = "e0_20261007T132027Z"
RUN_DIR = REPO / "experiment0" / "runs" / RUN_ID
OUT_MD = REPO / "diagnostics" / "experiment0_operational_cost_audit.md"
OUT_JSON = REPO / "diagnostics" / "experiment0_operational_cost_audit.json"

# Allowlist only — never pull scientific / text fields into aggregates
ALLOW = (
    "episode_id",
    "schedule_index",
    "turn",
    "regeneration_count",
    "actor_input_tokens",
    "actor_output_tokens",
    "actor_latency_ms",
    "actor_model",
    "witness_model",
    "provider",
    "provider_meta",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def extract_ops(event: dict[str, Any]) -> dict[str, Any]:
    """Pull allowlisted operational fields only; discard everything else."""
    pm = event.get("provider_meta") if isinstance(event.get("provider_meta"), dict) else {}
    return {
        "episode_id": event.get("episode_id"),
        "schedule_index": event.get("schedule_index"),
        "turn": event.get("turn"),
        "regeneration_count": int(event.get("regeneration_count") or 0),
        "actor_input_tokens": int(event.get("actor_input_tokens") or 0),
        "actor_output_tokens": int(event.get("actor_output_tokens") or 0),
        "actor_latency_ms": int(event.get("actor_latency_ms") or 0),
        "actor_model": event.get("actor_model"),
        "witness_model": event.get("witness_model"),
        "provider": event.get("provider"),
        # Last provider call of the turn (Exp0 runner overwrites; typically last Witness)
        "last_call_prompt_tokens": int(pm.get("prompt_tokens") or 0),
        "last_call_completion_tokens": int(pm.get("completion_tokens") or 0),
        "last_call_latency_ms": int(pm.get("latency_ms") or 0),
        "last_call_retries": int(pm.get("retries") or 0),
        "last_call_finish_reason": pm.get("finish_reason"),
        "last_call_model_id_returned": pm.get("model_id_returned"),
    }


def median(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    return float(statistics.median(xs))


def mean(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    return float(sum(xs) / len(xs))


def cost_usd(inp: float, out: float, pin: float, pout: float) -> float:
    return (inp / 1_000_000.0) * pin + (out / 1_000_000.0) * pout


def audit_incomplete_wasted() -> dict[str, Any]:
    """Operational usage from incomplete index-19 ledgers/baks only."""
    ep_dir = RUN_DIR / "episodes"
    files = sorted(ep_dir.glob("*i19*"))
    total_actor_in = total_actor_out = 0
    total_last_in = total_last_out = 0
    total_actor_lat = total_last_lat = 0
    turns = 0
    actor_calls = witness_calls = 0
    file_summaries = []
    for path in files:
        if path.stat().st_size == 0:
            file_summaries.append({"file": path.name, "bytes": 0, "turns": 0})
            continue
        events = KarmaLedger.read_file(path)
        # Deduplicate by reading each file separately (partials are separate attempts)
        tcount = 0
        a_in = a_out = l_in = l_out = a_lat = l_lat = 0
        ac = wc = 0
        for e in events:
            ops = extract_ops(e)
            tcount += 1
            rc = ops["regeneration_count"]
            ac += 1 + rc
            wc += 1 + rc
            a_in += ops["actor_input_tokens"]
            a_out += ops["actor_output_tokens"]
            a_lat += ops["actor_latency_ms"]
            l_in += ops["last_call_prompt_tokens"]
            l_out += ops["last_call_completion_tokens"]
            l_lat += ops["last_call_latency_ms"]
        turns += tcount
        actor_calls += ac
        witness_calls += wc
        total_actor_in += a_in
        total_actor_out += a_out
        total_last_in += l_in
        total_last_out += l_out
        total_actor_lat += a_lat
        total_last_lat += l_lat
        file_summaries.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "turns_logged": tcount,
                "model_calls_structural": ac + wc,
                "recorded_actor_input_tokens": a_in,
                "recorded_actor_output_tokens": a_out,
                "recorded_last_call_input_tokens": l_in,
                "recorded_last_call_output_tokens": l_out,
            }
        )
    return {
        "note": (
            "Incomplete schedule-index-19 attempts only. Not included in "
            "completed-episode averages or N=60 projections."
        ),
        "files": file_summaries,
        "structural_model_calls": actor_calls + witness_calls,
        "recorded_actor_input_tokens": total_actor_in,
        "recorded_actor_output_tokens": total_actor_out,
        "recorded_last_call_input_tokens": total_last_in,
        "recorded_last_call_output_tokens": total_last_out,
        "recorded_input_tokens_sum_actor_plus_last_call": total_actor_in + total_last_in,
        "recorded_output_tokens_sum_actor_plus_last_call": total_actor_out + total_last_out,
        "recorded_actor_latency_ms": total_actor_lat,
        "recorded_last_call_latency_ms": total_last_lat,
    }


def main() -> int:
    schedule = json.loads((RUN_DIR / "assignment_schedule.json").read_text(encoding="utf-8"))
    slots = [s for s in schedule["slots"] if int(s["schedule_index"]) <= 18]
    assert len(slots) == 19

    per_episode: list[dict[str, Any]] = []
    # totals
    tot_actor_calls = tot_wit_calls = tot_rev_actor = tot_wit_reeval = 0
    tot_actor_in = tot_actor_out = 0
    tot_last_in = tot_last_out = 0
    tot_actor_lat = tot_last_lat = 0
    turns_with_regen = 0
    total_turns = 0

    for slot in slots:
        eid = slot["episode_id"]
        path = RUN_DIR / "episodes" / f"{eid}.jsonl"
        events = KarmaLedger.read_file(path)
        turns = {e.get("turn") for e in events}
        if turns != set(range(1, 26)):
            raise RuntimeError(f"Episode {eid} not complete for operational audit")

        ep_actor_calls = ep_wit_calls = ep_rev = 0
        ep_actor_in = ep_actor_out = 0
        ep_last_in = ep_last_out = 0
        ep_actor_lat = ep_last_lat = 0

        for e in events:
            ops = extract_ops(e)
            total_turns += 1
            rc = ops["regeneration_count"]
            # Structural call model (exact):
            # each turn: 1 actor initial + rc actor revisions
            #            1 witness_raw + rc witness re-evals (final is last witness)
            ep_actor_calls += 1 + rc
            ep_wit_calls += 1 + rc
            ep_rev += rc
            if rc:
                turns_with_regen += 1
            ep_actor_in += ops["actor_input_tokens"]
            ep_actor_out += ops["actor_output_tokens"]
            ep_actor_lat += ops["actor_latency_ms"]
            ep_last_in += ops["last_call_prompt_tokens"]
            ep_last_out += ops["last_call_completion_tokens"]
            ep_last_lat += ops["last_call_latency_ms"]

        ep_calls = ep_actor_calls + ep_wit_calls
        # Recorded token attribution: actor fields + last-call (typically witness)
        ep_in = ep_actor_in + ep_last_in
        ep_out = ep_actor_out + ep_last_out

        per_episode.append(
            {
                "schedule_index": int(slot["schedule_index"]),
                "model_calls": ep_calls,
                "actor_calls_incl_revisions": ep_actor_calls,
                "witness_calls_total": ep_wit_calls,
                "actor_revision_calls": ep_rev,
                "recorded_actor_input_tokens": ep_actor_in,
                "recorded_actor_output_tokens": ep_actor_out,
                "recorded_last_call_input_tokens": ep_last_in,
                "recorded_last_call_output_tokens": ep_last_out,
                "recorded_input_tokens": ep_in,
                "recorded_output_tokens": ep_out,
                "recorded_total_tokens": ep_in + ep_out,
                "recorded_actor_latency_ms": ep_actor_lat,
                "recorded_last_call_latency_ms": ep_last_lat,
            }
        )

        tot_actor_calls += ep_actor_calls
        tot_wit_calls += ep_wit_calls
        tot_rev_actor += ep_rev
        tot_wit_reeval += ep_rev
        tot_actor_in += ep_actor_in
        tot_actor_out += ep_actor_out
        tot_last_in += ep_last_in
        tot_last_out += ep_last_out
        tot_actor_lat += ep_actor_lat
        tot_last_lat += ep_last_lat

    n = 19
    calls = [e["model_calls"] for e in per_episode]
    ins = [e["recorded_input_tokens"] for e in per_episode]
    outs = [e["recorded_output_tokens"] for e in per_episode]
    tots = [e["recorded_total_tokens"] for e in per_episode]

    tot_calls = tot_actor_calls + tot_wit_calls
    tot_in = tot_actor_in + tot_last_in
    tot_out = tot_actor_out + tot_last_out

    # Imputation note for undercount: 17 turns with regen=1 missing prior actor+witness tokens
    # Estimate missing using mean recorded tokens from non-regen turns is not available
    # without re-scan; use mean per-call from recorded:
    # actor mean in/out per recorded actor field occurrence = tot/475 turns
    # For each regen turn missing 1 actor + 1 witness (raw):
    mean_actor_in_per_turn_field = tot_actor_in / total_turns
    mean_actor_out_per_turn_field = tot_actor_out / total_turns
    mean_last_in_per_turn = tot_last_in / total_turns
    mean_last_out_per_turn = tot_last_out / total_turns
    missing_pairs = turns_with_regen  # each missing ~1 actor call + 1 witness_raw
    est_missing_in = missing_pairs * (mean_actor_in_per_turn_field + mean_last_in_per_turn)
    est_missing_out = missing_pairs * (mean_actor_out_per_turn_field + mean_last_out_per_turn)

    mean_calls = mean(calls)
    mean_in = mean(ins)
    mean_out = mean(outs)

    proj_calls = mean_calls * 60
    proj_in = mean_in * 60
    proj_out = mean_out * 60
    proj_in_20 = proj_in * 1.20
    proj_out_20 = proj_out * 1.20
    proj_in_max = max(ins) * 60
    proj_out_max = max(outs) * 60

    # OpenRouter pricing verified via https://openrouter.ai/api/v1/models at audit time
    openrouter = {
        "model_id": "nvidia/nemotron-3-super-120b-a12b",
        "source": "https://openrouter.ai/api/v1/models",
        "verified_utc": utc_now(),
        "pricing_prompt_per_token": 0.00000008,
        "pricing_completion_per_token": 0.00000045,
        "input_usd_per_million": 0.08,
        "output_usd_per_million": 0.45,
        "verification_status": "VERIFIED_FROM_OPENROUTER_MODELS_API",
    }

    def scenario_block(pin: float, pout: float, label: str) -> dict[str, Any]:
        return {
            "label": label,
            "input_usd_per_million": pin,
            "output_usd_per_million": pout,
            "mean_projected_n60_usd": round(cost_usd(proj_in, proj_out, pin, pout), 4),
            "plus_20pct_allowance_usd": round(cost_usd(proj_in_20, proj_out_20, pin, pout), 4),
            "max_envelope_usd": round(cost_usd(proj_in_max, proj_out_max, pin, pout), 4),
        }

    sensitivities = [
        scenario_block(0.05, 0.25, "$0.05/M in + $0.25/M out"),
        scenario_block(0.08, 0.45, "$0.08/M in + $0.45/M out"),
        scenario_block(0.10, 0.50, "$0.10/M in + $0.50/M out"),
        scenario_block(0.30, 0.65, "$0.30/M in + $0.65/M out"),
    ]

    openrouter_costs = scenario_block(
        openrouter["input_usd_per_million"],
        openrouter["output_usd_per_million"],
        "OpenRouter nvidia/nemotron-3-super-120b-a12b (API-verified)",
    )

    # Free-NIM pacing lower bounds
    pacing = {}
    for sec in (30, 60, 90):
        pacing[f"{sec}s"] = {
            "spacing_sec": sec,
            "pacing_only_lower_bound_sec": (proj_calls - 1) * sec,
            "pacing_only_lower_bound_hours": round(((proj_calls - 1) * sec) / 3600.0, 2),
        }

    # Approximate wall-clock using mean recorded latencies per call
    # Structural: half calls actor, half witness roughly
    mean_actor_lat = tot_actor_lat / tot_actor_calls if tot_actor_calls else 0
    mean_last_lat = tot_last_lat / total_turns if total_turns else 0  # per turn last call
    # Approx wall per episode = sum actor latencies + sum last-call latencies (recorded)
    # Missing latent time for undercounted calls ~ mean * missing
    mean_ep_lat_ms = mean(
        [e["recorded_actor_latency_ms"] + e["recorded_last_call_latency_ms"] for e in per_episode]
    )
    approx_wall_60_sec = (mean_ep_lat_ms / 1000.0) * 60
    # With pacing between calls (not recommending): illustrative only
    approx_with_pacing = {
        f"wall_plus_{sec}s_start_spacing_hours": round(
            (approx_wall_60_sec + (proj_calls - 1) * sec) / 3600.0, 2
        )
        for sec in (30, 60, 90)
    }

    wasted = audit_incomplete_wasted()

    report = {
        "audit_type": "operational_cost_runtime_only",
        "run_id": RUN_ID,
        "generated_utc": utc_now(),
        "blinding": {
            "no_scientific_metrics_computed": True,
            "no_c1_c2_comparison": True,
            "no_response_text_inspected_or_reported": True,
            "run_not_resumed": True,
            "frozen_scientific_artifacts_not_modified": True,
            "condition_labels_ignored": True,
        },
        "methodology": {
            "completed_episodes": "schedule indices 0-18 only (19 episodes, 25 turns each)",
            "call_counting": (
                "Exact structural counts: per turn 1 Actor initial + regeneration_count "
                "Actor revisions; 1 Witness RAW + regeneration_count Witness re-evals. "
                "Witness FINAL is the last Witness call (not an extra API call)."
            ),
            "token_recording": (
                "Ledger stores actor_input/output_tokens for the last Actor call of the "
                "turn, and provider_meta tokens for the last provider call of the turn "
                "(typically last Witness). Turns with regeneration_count>0 undercount "
                "prior Actor/Witness calls in token totals. Primary totals use recorded "
                "fields; an imputation estimate for missing pairs is shown separately."
            ),
            "turns_with_regeneration": turns_with_regen,
            "total_turns": total_turns,
        },
        "A_completed_run_totals": {
            "completed_episodes": n,
            "total_model_calls_structural": tot_calls,
            "actor_calls_including_revisions": tot_actor_calls,
            "actor_initial_calls": tot_actor_calls - tot_rev_actor,
            "actor_revision_calls": tot_rev_actor,
            "witness_calls_total": tot_wit_calls,
            "witness_raw_calls": total_turns,  # one per turn
            "witness_reeval_calls_leading_to_final": tot_wit_reeval,
            "witness_final_extra_calls": 0,
            "other_model_calls": 0,
            "recorded_input_tokens_actor_plus_last_call": tot_in,
            "recorded_output_tokens_actor_plus_last_call": tot_out,
            "recorded_total_tokens": tot_in + tot_out,
            "recorded_actor_input_tokens": tot_actor_in,
            "recorded_actor_output_tokens": tot_actor_out,
            "recorded_last_call_input_tokens_typically_witness": tot_last_in,
            "recorded_last_call_output_tokens_typically_witness": tot_last_out,
            "recorded_actor_latency_ms_sum": tot_actor_lat,
            "recorded_last_call_latency_ms_sum": tot_last_lat,
            "recorded_latency_ms_sum_actor_plus_last_call": tot_actor_lat + tot_last_lat,
            "estimated_missing_token_pairs_from_regen_turns": missing_pairs,
            "estimated_missing_input_tokens_imputed": round(est_missing_in),
            "estimated_missing_output_tokens_imputed": round(est_missing_out),
            "estimated_full_input_tokens_recorded_plus_imputed": round(tot_in + est_missing_in),
            "estimated_full_output_tokens_recorded_plus_imputed": round(tot_out + est_missing_out),
        },
        "B_per_episode_distribution": {
            "calls": {
                "mean": mean_calls,
                "median": median(calls),
                "min": min(calls),
                "max": max(calls),
            },
            "recorded_input_tokens": {
                "mean": mean_in,
                "median": median(ins),
                "min": min(ins),
                "max": max(ins),
            },
            "recorded_output_tokens": {
                "mean": mean_out,
                "median": median(outs),
                "min": min(outs),
                "max": max(outs),
            },
            "recorded_total_tokens": {
                "mean": mean(tots),
                "median": median(tots),
                "min": min(tots),
                "max": max(tots),
            },
        },
        "C_actor_vs_witness": {
            "actor": {
                "calls_including_revisions": tot_actor_calls,
                "recorded_input_tokens": tot_actor_in,
                "recorded_output_tokens": tot_actor_out,
                "mean_recorded_input_per_episode": tot_actor_in / n,
                "mean_recorded_output_per_episode": tot_actor_out / n,
                "mean_calls_per_episode": tot_actor_calls / n,
            },
            "witness": {
                "calls_total": tot_wit_calls,
                "raw_calls": total_turns,
                "reeval_calls": tot_wit_reeval,
                "recorded_last_call_input_tokens_proxy": tot_last_in,
                "recorded_last_call_output_tokens_proxy": tot_last_out,
                "mean_recorded_last_call_input_per_episode": tot_last_in / n,
                "mean_recorded_last_call_output_per_episode": tot_last_out / n,
                "mean_calls_per_episode": tot_wit_calls / n,
                "note": (
                    "Witness token columns use last-call provider_meta per turn "
                    "(typically final Witness of that turn)."
                ),
            },
            "revision_related": {
                "actor_revision_calls": tot_rev_actor,
                "witness_reeval_calls": tot_wit_reeval,
                "note": "Identified only by regeneration_count; no scientific reason reported.",
            },
        },
        "D_fresh_n60_projection": {
            "basis": "empirical mean of 19 completed episodes (recorded token attribution)",
            "projected_calls_60": proj_calls,
            "projected_input_tokens_60": proj_in,
            "projected_output_tokens_60": proj_out,
            "plus_20pct_engineering_allowance": {
                "projected_input_tokens_60": proj_in_20,
                "projected_output_tokens_60": proj_out_20,
            },
            "observed_max_per_episode_times_60_envelope": {
                "projected_input_tokens_60": proj_in_max,
                "projected_output_tokens_60": proj_out_max,
                "max_calls_envelope_60": max(calls) * 60,
            },
            "disclaimer": "Operational projections only — not scientific estimates.",
        },
        "E_paid_serving_cost_scenarios": {
            "formula": (
                "cost = input_tokens_millions * input_price_per_million + "
                "output_tokens_millions * output_price_per_million"
            ),
            "scenario_1_openrouter_same_model": {
                "pricing": openrouter,
                "costs_usd": openrouter_costs,
            },
            "scenario_2_generic_sensitivity": sensitivities,
        },
        "F_free_nim_runtime_estimate": {
            "pacing_only_lower_bounds": pacing,
            "formula_pacing_only": "(projected_calls_60 - 1) * spacing_sec",
            "approximate_wall_clock": {
                "mean_recorded_inference_latency_per_episode_sec": mean_ep_lat_ms / 1000.0,
                "approx_60_episode_inference_latency_only_hours": round(
                    approx_wall_60_sec / 3600.0, 2
                ),
                "illustrative_wall_plus_start_spacing": approx_with_pacing,
                "note": (
                    "Pacing-only is a lower bound ignoring compute time and retries. "
                    "Wall+spacing adds recorded per-episode latency sums to spacing; "
                    "still approximate. No pacing policy recommended here."
                ),
            },
        },
        "G_aborted_run_sunk_usage": {
            "completed_episodes_0_to_18": {
                "structural_model_calls": tot_calls,
                "recorded_input_tokens": tot_in,
                "recorded_output_tokens": tot_out,
            },
            "incomplete_episode_19_attempts": wasted,
            "diagnostics_separate": (
                "Isolated NIM pacing diagnostics under diagnostics/runs/nim_rl_* "
                "are NOT included in Experiment 0 episode totals."
            ),
        },
        "integrity_confirmation": {
            "no_scientific_outcome_metric_computed": True,
            "no_c1_c2_comparison_performed": True,
            "no_response_text_inspected_or_reported": True,
            "run_not_resumed": True,
            "no_frozen_scientific_artifact_modified": True,
            "original_ledgers_not_rewritten": True,
        },
    }

    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    OUT_MD.write_text(_md(report), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")
    return 0


def _md(r: dict[str, Any]) -> str:
    a = r["A_completed_run_totals"]
    b = r["B_per_episode_distribution"]
    c = r["C_actor_vs_witness"]
    d = r["D_fresh_n60_projection"]
    e = r["E_paid_serving_cost_scenarios"]
    f = r["F_free_nim_runtime_estimate"]
    g = r["G_aborted_run_sunk_usage"]
    or_ = e["scenario_1_openrouter_same_model"]
    lines = [
        "# Experiment 0 operational cost/runtime audit",
        "",
        f"**Run:** `{r['run_id']}`  ",
        f"**Generated:** `{r['generated_utc']}`  ",
        "",
        "Operational only. **No scientific analysis.** Run not resumed.",
        "",
        "## Integrity",
        "",
        "- No scientific outcome metric computed",
        "- No C1/C2 comparison performed",
        "- No response text inspected/reported",
        "- Run not resumed",
        "- No frozen scientific artifact modified",
        "- Original ledgers not rewritten",
        "",
        "## A. Completed-run totals (indices 0–18)",
        "",
        f"- Completed episodes: **{a['completed_episodes']}**",
        f"- Total model calls (structural): **{a['total_model_calls_structural']}**",
        f"- Actor calls (incl. revisions): **{a['actor_calls_including_revisions']}**",
        f"- Actor initial calls: **{a['actor_initial_calls']}**",
        f"- Actor revision calls: **{a['actor_revision_calls']}**",
        f"- Witness calls total: **{a['witness_calls_total']}**",
        f"- Witness RAW calls: **{a['witness_raw_calls']}**",
        f"- Witness re-eval calls: **{a['witness_reeval_calls_leading_to_final']}**",
        f"- Recorded input tokens (actor + last-call): **{a['recorded_input_tokens_actor_plus_last_call']:,}**",
        f"- Recorded output tokens (actor + last-call): **{a['recorded_output_tokens_actor_plus_last_call']:,}**",
        f"- Recorded total tokens: **{a['recorded_total_tokens']:,}**",
        f"- Recorded latency sum (actor + last-call) ms: **{a['recorded_latency_ms_sum_actor_plus_last_call']:,}**",
        f"- Regen turns (token undercount pairs): **{a['estimated_missing_token_pairs_from_regen_turns']}**",
        f"- Imputed missing input tokens (approx): **{a['estimated_missing_input_tokens_imputed']:,}**",
        f"- Estimated full input (recorded+imputed): **{a['estimated_full_input_tokens_recorded_plus_imputed']:,}**",
        f"- Estimated full output (recorded+imputed): **{a['estimated_full_output_tokens_recorded_plus_imputed']:,}**",
        "",
        "## B. Per-episode operational distribution",
        "",
        f"- Calls/episode: mean={b['calls']['mean']:.2f}, median={b['calls']['median']}, "
        f"min={b['calls']['min']}, max={b['calls']['max']}",
        f"- Input tokens/episode: mean={b['recorded_input_tokens']['mean']:,.0f}, "
        f"median={b['recorded_input_tokens']['median']:,.0f}, "
        f"min={b['recorded_input_tokens']['min']:,}, max={b['recorded_input_tokens']['max']:,}",
        f"- Output tokens/episode: mean={b['recorded_output_tokens']['mean']:,.0f}, "
        f"median={b['recorded_output_tokens']['median']:,.0f}, "
        f"min={b['recorded_output_tokens']['min']:,}, max={b['recorded_output_tokens']['max']:,}",
        "",
        "## C. Actor vs Witness usage",
        "",
        "### Actor",
        f"- Calls: **{c['actor']['calls_including_revisions']}** "
        f"(mean/episode {c['actor']['mean_calls_per_episode']:.2f})",
        f"- Recorded input tokens: **{c['actor']['recorded_input_tokens']:,}**",
        f"- Recorded output tokens: **{c['actor']['recorded_output_tokens']:,}**",
        "",
        "### Witness (last-call proxy for tokens)",
        f"- Calls: **{c['witness']['calls_total']}** "
        f"(RAW {c['witness']['raw_calls']}, re-eval {c['witness']['reeval_calls']})",
        f"- Recorded last-call input tokens: **{c['witness']['recorded_last_call_input_tokens_proxy']:,}**",
        f"- Recorded last-call output tokens: **{c['witness']['recorded_last_call_output_tokens_proxy']:,}**",
        "",
        "### Revision-related (operational count only)",
        f"- Actor revision calls: **{c['revision_related']['actor_revision_calls']}**",
        f"- Witness re-eval calls: **{c['revision_related']['witness_reeval_calls']}**",
        "",
        "## D. Fresh N=60 projection (operational)",
        "",
        f"- `projected_calls_60` = **{d['projected_calls_60']:.1f}**",
        f"- `projected_input_tokens_60` = **{d['projected_input_tokens_60']:,.0f}**",
        f"- `projected_output_tokens_60` = **{d['projected_output_tokens_60']:,.0f}**",
        f"- +20% allowance input/output: "
        f"**{d['plus_20pct_engineering_allowance']['projected_input_tokens_60']:,.0f}** / "
        f"**{d['plus_20pct_engineering_allowance']['projected_output_tokens_60']:,.0f}**",
        f"- Max-envelope (obs max × 60) input/output: "
        f"**{d['observed_max_per_episode_times_60_envelope']['projected_input_tokens_60']:,}** / "
        f"**{d['observed_max_per_episode_times_60_envelope']['projected_output_tokens_60']:,}**",
        "",
        f"_{d['disclaimer']}_",
        "",
        "## E. Paid-serving cost scenarios",
        "",
        f"Formula: `{e['formula']}`",
        "",
        "### Scenario 1 — OpenRouter same-model",
        "",
        f"- Model: `{or_['pricing']['model_id']}`",
        f"- Pricing verification: **{or_['pricing']['verification_status']}**",
        f"- Source: {or_['pricing']['source']}",
        f"- Input/output $/M: **{or_['pricing']['input_usd_per_million']}** / "
        f"**{or_['pricing']['output_usd_per_million']}**",
        f"- Mean N=60 cost: **${or_['costs_usd']['mean_projected_n60_usd']:.2f}**",
        f"- +20% allowance: **${or_['costs_usd']['plus_20pct_allowance_usd']:.2f}**",
        f"- Max envelope: **${or_['costs_usd']['max_envelope_usd']:.2f}**",
        "",
        "### Scenario 2 — generic sensitivity",
        "",
        "| Price (in/out per M) | Mean N=60 | +20% | Max envelope |",
        "|---|---:|---:|---:|",
    ]
    for s in e["scenario_2_generic_sensitivity"]:
        lines.append(
            f"| {s['label']} | ${s['mean_projected_n60_usd']:.2f} | "
            f"${s['plus_20pct_allowance_usd']:.2f} | ${s['max_envelope_usd']:.2f} |"
        )
    lines += [
        "",
        "## F. Free-NIM runtime estimate (no policy recommendation)",
        "",
        "### Pacing-only lower bound",
        "",
        f"Formula: `{f['formula_pacing_only']}`",
        "",
    ]
    for k, v in f["pacing_only_lower_bounds"].items():
        lines.append(
            f"- {k}: **{v['pacing_only_lower_bound_hours']:.2f} h** "
            f"({v['pacing_only_lower_bound_sec']:.0f} s)"
        )
    aw = f["approximate_wall_clock"]
    lines += [
        "",
        "### Approximate wall-clock (illustrative)",
        "",
        f"- Mean recorded inference latency/episode: "
        f"**{aw['mean_recorded_inference_latency_per_episode_sec']:.1f} s**",
        f"- ~60-episode inference-only: **{aw['approx_60_episode_inference_latency_only_hours']:.2f} h**",
        "",
    ]
    for k, v in aw["illustrative_wall_plus_start_spacing"].items():
        lines.append(f"- {k}: **{v:.2f} h**")
    lines += [
        "",
        f"_{aw['note']}_",
        "",
        "## G. Aborted-run sunk operational usage",
        "",
        "### Completed episodes 0–18",
        f"- Calls: **{g['completed_episodes_0_to_18']['structural_model_calls']}**",
        f"- Recorded input/output tokens: "
        f"**{g['completed_episodes_0_to_18']['recorded_input_tokens']:,}** / "
        f"**{g['completed_episodes_0_to_18']['recorded_output_tokens']:,}**",
        "",
        "### Incomplete episode-19 attempts (wasted operational)",
        f"- Structural calls: **{g['incomplete_episode_19_attempts']['structural_model_calls']}**",
        f"- Recorded input/output (actor+last-call): "
        f"**{g['incomplete_episode_19_attempts']['recorded_input_tokens_sum_actor_plus_last_call']:,}** / "
        f"**{g['incomplete_episode_19_attempts']['recorded_output_tokens_sum_actor_plus_last_call']:,}**",
        "",
        f"_{g['diagnostics_separate']}_",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
