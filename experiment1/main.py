#!/usr/bin/env python3
"""Experiment 1 harness entrypoint.

Modes:
  python main.py --mode pilot    # 15 pilot episodes (5 per condition)
  python main.py --mode check    # pilot checklist only
  python main.py --mode main     # 150 main episodes (50 per condition)
  python main.py --mode extract  # extract metrics from completed runs

Fail-and-restart only (PATCH 2). No unsafe partial resume.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure experiment1 root is on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.experiment_config import (
    CONTEXT_CAPACITY_FRACTION,
    DOCUMENTS_DIR,
    DOCUMENT_HASHES,
    MAX_TOKENS_ACTOR,
    MODEL_CONTEXT_LIMIT,
    N_EPISODES_PER_CONDITION,
    N_PILOT_EPISODES_PER_CONDITION,
    RUNS_DIR,
    SOURCE_HASHES,
    TOTAL_TURNS,
)
from src.actor import Actor, build_actor_system_prompt, validate_actor_system_prompt
from src.buddhi import Buddhi
from src.episode_runner import (
    EpisodeFailedError,
    EpisodeRunner,
    UnsafeResumeError,
    make_episode_id,
    make_replacement_episode_id,
)
from src.karma_ledger import KarmaLedger
from src.metric_extractor import extract_directory
from src.osm import OSM
from src.pilot_checker import run_pilot_checks, write_pilot_report
from src.script_loader import ScriptLoader, validate_frozen_stimuli
from src.types_util import (
    assert_sources_not_placeholders,
    build_source_packet,
    estimate_tokens,
    load_text,
    validate_input_integrity,
)
from src.witness import Witness

MAIN_RUN_MANIFEST_NAME = "main_run_manifest.json"


def generate_seed_manifest(
    n_per_condition: int,
    output_path: Path,
    *,
    master_seed: int = 42,
) -> dict[str, list[int]]:
    """Generate episode assignment seeds. Save BEFORE any episodes run.

    These seeds do NOT control Claude sampling. They are assignment/order/audit seeds.
    """
    output_path = Path(output_path)
    if output_path.exists():
        data = json.loads(output_path.read_text(encoding="utf-8"))
        return {str(k): v for k, v in data["seeds"].items()}

    rng = random.Random(master_seed)
    seeds = {
        str(condition): [
            rng.randint(10000, 99999) for _ in range(n_per_condition)
        ]
        for condition in [1, 2, 3]
    }
    manifest = {
        "description": (
            "Episode randomization manifest seeds for assignment tracking. "
            "These seeds do NOT control Claude model sampling reproducibility."
        ),
        "master_seed": master_seed,
        "n_per_condition": n_per_condition,
        "seeds": seeds,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return seeds


def context_capacity_preflight(
    actor_system_prompt: str,
    witness_system_prompt: str,
    source_packet_text: str,
) -> None:
    """Conservative upper-bound context estimate. Raise — never truncate."""
    actor_estimate = (
        estimate_tokens(actor_system_prompt)
        + TOTAL_TURNS * MAX_TOKENS_ACTOR
        + TOTAL_TURNS * MAX_TOKENS_ACTOR
        + TOTAL_TURNS * 100
        + 2000
    )
    witness_estimate = (
        estimate_tokens(witness_system_prompt)
        + estimate_tokens(source_packet_text)
        + MAX_TOKENS_ACTOR
        + 500
    )
    limit = int(MODEL_CONTEXT_LIMIT * CONTEXT_CAPACITY_FRACTION)
    if actor_estimate > limit or witness_estimate > limit:
        raise RuntimeError(
            "Frozen experiment context exceeds model context capacity. "
            "Do not truncate, summarize, or drop history. "
            "Reduce source text or adjust token limits in a new preregistration.\n"
            f"actor_estimate={actor_estimate}, witness_estimate={witness_estimate}, "
            f"limit_90pct={limit}"
        )


def _make_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is required for live runs."
        )
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def startup_experimental_blockers() -> dict[str, str]:
    """Run all hard blockers required before pilot/main.

    Order: hash integrity → placeholder sources → frozen stimuli → actor isolation.
    """
    input_hashes = validate_input_integrity()
    assert_sources_not_placeholders()
    validate_frozen_stimuli()

    constitution = load_text(DOCUMENTS_DIR / "actor_constitution_v1.md")
    source_packet = build_source_packet()
    # Full system prompt isolation scan (PATCH 4) — fails on current constitution
    build_actor_system_prompt(constitution, source_packet)
    return input_hashes


def _prepare_components(client: Any) -> tuple[str, str, dict[str, str]]:
    constitution = load_text(DOCUMENTS_DIR / "actor_constitution_v1.md")
    source_packet = build_source_packet()
    actor_system = build_actor_system_prompt(constitution, source_packet)
    witness_protocol = load_text(DOCUMENTS_DIR / "witness_protocol_v1.md")
    w = Witness(client, witness_protocol, source_packet)
    context_capacity_preflight(actor_system, w.system_prompt, source_packet)
    return actor_system, source_packet, {
        "constitution": constitution,
        "witness_protocol": witness_protocol,
    }


def _write_failed_marker(
    output_dir: Path,
    episode_id: str,
    reason: str,
    *,
    turns_logged: int,
) -> Path:
    fail_path = output_dir / f"{episode_id}.FAILED.json"
    payload = {
        "status": "failed",
        "episode_id": episode_id,
        "error": reason,
        "turns_logged": turns_logged,
        "resume_allowed": False,
        "policy": "fail-and-restart",
    }
    fail_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return fail_path


def _ledger_is_complete(path: Path) -> bool:
    if not path.exists():
        return False
    ledger = KarmaLedger(path, create_new=True)
    return ledger.turn_count() >= TOTAL_TURNS


def _ledger_is_partial(path: Path) -> bool:
    if not path.exists():
        return False
    ledger = KarmaLedger(path, create_new=True)
    n = ledger.turn_count()
    return 0 < n < TOTAL_TURNS


def assert_main_run_not_completed(output_dir: Path, *, allow_new: bool) -> Path:
    """Abort if a completed main run already exists, unless override.

    Override requires a separate run directory (never reuse/overwrite).
    """
    output_dir = Path(output_dir)
    manifest_path = output_dir / MAIN_RUN_MANIFEST_NAME
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("status") == "completed":
            if not allow_new:
                raise RuntimeError(
                    f"Completed main run already exists at {manifest_path}. "
                    "Refusing to rerun. Pass --allow-new-main-run to create a "
                    "SEPARATE run directory (existing results are never overwritten)."
                )
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            new_dir = output_dir.parent / f"main_run_{ts}"
            new_dir.mkdir(parents=True, exist_ok=False)
            return new_dir
    return output_dir


def write_main_run_manifest(output_dir: Path, *, status: str, **extra: Any) -> None:
    path = Path(output_dir) / MAIN_RUN_MANIFEST_NAME
    payload = {
        "status": status,
        "n_per_condition": N_EPISODES_PER_CONDITION,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_episodes(
    mode: str,
    n_per_condition: int,
    output_dir: Path,
    *,
    client: Optional[Any] = None,
    replace_failed_id: Optional[str] = None,
) -> list[Path]:
    """Run episodes for all three conditions. Seed manifest written first.

    Fail-and-restart: partial ledgers are never resumed with empty Actor history.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_hashes = startup_experimental_blockers()

    seed_path = output_dir / "seed_manifest.json"
    seeds = generate_seed_manifest(n_per_condition, seed_path)

    client = client or _make_client()
    actor_system, source_packet, docs = _prepare_components(client)

    constitution_hash = DOCUMENT_HASHES["actor_constitution_v1.md"]
    witness_protocol_hash = DOCUMENT_HASHES["witness_protocol_v1.md"]
    script_hash = DOCUMENT_HASHES["conversation_script_v1.md"]
    source_hashes = dict(SOURCE_HASHES)

    script = ScriptLoader()
    buddhi = Buddhi()
    written: list[Path] = []
    history_captures: dict[str, Any] = {
        "turn10_messages": {},
        "turn9_responses": {},
    }

    # Explicit single-episode replacement (operator action only)
    if replace_failed_id:
        return [
            _run_replacement_episode(
                mode=mode,
                failed_episode_id=replace_failed_id,
                output_dir=output_dir,
                client=client,
                actor_system=actor_system,
                source_packet=source_packet,
                docs=docs,
                script=script,
                buddhi=buddhi,
                input_hashes=input_hashes,
                constitution_hash=constitution_hash,
                witness_protocol_hash=witness_protocol_hash,
                script_hash=script_hash,
                source_hashes=source_hashes,
                seeds=seeds,
                history_captures=history_captures,
            )
        ]

    for condition in (1, 2, 3):
        for seed in seeds[str(condition)]:
            # Prefer stable planned stem for lookup; UUID still unique per attempt
            episode_id = make_episode_id(mode, condition, seed)
            ledger_path = output_dir / f"{episode_id}.jsonl"

            # Never resume partials. Detect any partial ledger for this
            # condition/seed via FAILED markers / partial files.
            partials = list(output_dir.glob(f"{mode}_{condition}_{seed}_*.jsonl"))
            skip = False
            for p in partials:
                if _ledger_is_complete(p):
                    written.append(p)
                    skip = True
                    break
                if _ledger_is_partial(p):
                    # Leave intact for audit; do not append/resume
                    _write_failed_marker(
                        output_dir,
                        p.stem,
                        "partial episode — resume forbidden (fail-and-restart)",
                        turns_logged=KarmaLedger(p, create_new=True).turn_count(),
                    )
                    skip = True
                    print(
                        f"SKIP partial (no resume): {p.name}",
                        file=sys.stderr,
                    )
                    break
            if skip:
                continue

            actor = Actor(client, actor_system)
            witness = Witness(client, docs["witness_protocol"], source_packet)
            osm = OSM()
            # create_new=False would fail if exists; we already skipped existings
            if ledger_path.exists():
                # Extremely unlikely UUID collision — do not overwrite
                raise RuntimeError(f"Ledger path already exists: {ledger_path}")
            ledger = KarmaLedger(ledger_path, create_new=True)

            runner = EpisodeRunner(
                actor=actor,
                witness=witness,
                buddhi=buddhi,
                osm=osm,
                script=script,
                ledger=ledger,
                condition=condition,
                seed=seed,
                episode_id=episode_id,
                input_hashes=input_hashes,
                constitution_hash=constitution_hash,
                witness_protocol_hash=witness_protocol_hash,
                script_hash=script_hash,
                source_hashes=source_hashes,
            )
            try:
                path = runner.run()
                written.append(path)
                if runner.turn10_actor_messages is not None:
                    history_captures["turn10_messages"][episode_id] = (
                        runner.turn10_actor_messages
                    )
                if runner.turn9_user_response is not None:
                    history_captures["turn9_responses"][episode_id] = (
                        runner.turn9_user_response
                    )
            except (EpisodeFailedError, UnsafeResumeError) as e:
                _write_failed_marker(
                    output_dir,
                    episode_id,
                    str(e),
                    turns_logged=ledger.turn_count(),
                )
                print(f"FAILED: {e}", file=sys.stderr)

    capture_path = output_dir / "actor_history_captures.json"
    capture_path.write_text(
        json.dumps(history_captures, indent=2), encoding="utf-8"
    )
    return written


def _run_replacement_episode(
    *,
    mode: str,
    failed_episode_id: str,
    output_dir: Path,
    client: Any,
    actor_system: str,
    source_packet: str,
    docs: dict[str, str],
    script: ScriptLoader,
    buddhi: Buddhi,
    input_hashes: dict[str, str],
    constitution_hash: str,
    witness_protocol_hash: str,
    script_hash: str,
    source_hashes: dict[str, str],
    seeds: dict[str, list[int]],
    history_captures: dict[str, Any],
) -> Path:
    """Operator-triggered replacement: new ID, never touches failed ledger."""
    failed_ledger = output_dir / f"{failed_episode_id}.jsonl"
    failed_marker = output_dir / f"{failed_episode_id}.FAILED.json"
    if not failed_ledger.exists() and not failed_marker.exists():
        raise RuntimeError(
            f"Cannot replace unknown failed episode: {failed_episode_id}"
        )
    # Parse condition/seed from failed id: mode_condition_seed_...
    parts = failed_episode_id.split("_")
    if len(parts) < 3:
        raise RuntimeError(f"Unrecognized failed episode id: {failed_episode_id}")
    condition = int(parts[1])
    seed = int(parts[2])

    # Do not overwrite failed ledger
    if failed_ledger.exists():
        # Touch-read only
        _ = KarmaLedger.read_file(failed_ledger)

    new_id = make_replacement_episode_id(mode, condition, seed, failed_episode_id)
    new_path = output_dir / f"{new_id}.jsonl"
    if new_path.exists():
        raise RuntimeError(f"Replacement ledger already exists: {new_path}")

    meta_path = output_dir / f"{new_id}.REPLACEMENT.json"
    meta_path.write_text(
        json.dumps(
            {
                "replacement_attempt": True,
                "episode_id": new_id,
                "replaces_episode_id": failed_episode_id,
                "condition": condition,
                "seed": seed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    actor = Actor(client, actor_system)
    witness = Witness(client, docs["witness_protocol"], source_packet)
    ledger = KarmaLedger(new_path, create_new=True)
    runner = EpisodeRunner(
        actor=actor,
        witness=witness,
        buddhi=buddhi,
        osm=OSM(),
        script=script,
        ledger=ledger,
        condition=condition,
        seed=seed,
        episode_id=new_id,
        input_hashes=input_hashes,
        constitution_hash=constitution_hash,
        witness_protocol_hash=witness_protocol_hash,
        script_hash=script_hash,
        source_hashes=source_hashes,
        replaces_episode_id=failed_episode_id,
    )
    try:
        path = runner.run()
    except (EpisodeFailedError, UnsafeResumeError) as e:
        _write_failed_marker(
            output_dir, new_id, str(e), turns_logged=ledger.turn_count()
        )
        raise
    return path


def mode_pilot(client: Optional[Any] = None) -> None:
    run_episodes(
        "pilot",
        N_PILOT_EPISODES_PER_CONDITION,
        RUNS_DIR / "pilot",
        client=client,
    )


def mode_main(
    client: Optional[Any] = None,
    *,
    allow_new_main_run: bool = False,
) -> None:
    out = assert_main_run_not_completed(
        RUNS_DIR / "main", allow_new=allow_new_main_run
    )
    write_main_run_manifest(out, status="in_progress")
    try:
        written = run_episodes(
            "main",
            N_EPISODES_PER_CONDITION,
            out,
            client=client,
        )
        write_main_run_manifest(
            out,
            status="completed",
            episodes_written=len(written),
            run_dir=str(out),
        )
    except Exception:
        write_main_run_manifest(out, status="failed")
        raise


def mode_check() -> None:
    pilot_dir = RUNS_DIR / "pilot"
    enriched_dir = RUNS_DIR / "pilot_enriched"
    captures_path = pilot_dir / "actor_history_captures.json"
    turn10 = None
    turn9 = None
    if captures_path.exists():
        data = json.loads(captures_path.read_text(encoding="utf-8"))
        turn10 = data.get("turn10_messages")
        turn9 = data.get("turn9_responses")
    report = run_pilot_checks(
        pilot_dir,
        enriched_dir,
        turn10_messages_by_episode=turn10,
        turn9_responses_by_episode=turn9,
    )
    out = RUNS_DIR / "pilot" / "pilot_checklist_report.json"
    write_pilot_report(report, out)
    print(json.dumps(report.to_dict(), indent=2))
    if not report.all_passed:
        sys.exit(1)


def mode_extract() -> None:
    validate_input_integrity()
    for kind in ("pilot", "main"):
        src = RUNS_DIR / kind
        dst = RUNS_DIR / f"{kind}_enriched"
        if src.exists():
            written = extract_directory(src, dst)
            print(f"Extracted {len(written)} files -> {dst}")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Experiment 1 — Constitutional Governance Under Persistent Reward Pressure"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["pilot", "check", "main", "extract"],
        help="Execution mode",
    )
    parser.add_argument(
        "--allow-new-main-run",
        action="store_true",
        help=(
            "Administrative override: if a completed main run exists, create a "
            "SEPARATE run directory. Never overwrites existing results."
        ),
    )
    parser.add_argument(
        "--replace-failed",
        metavar="EPISODE_ID",
        default=None,
        help=(
            "Explicit operator action: start a replacement episode for a failed "
            "episode ID. New ledger + new ID; failed ledger untouched."
        ),
    )
    args = parser.parse_args(argv)

    if args.mode == "pilot":
        if args.replace_failed:
            run_episodes(
                "pilot",
                N_PILOT_EPISODES_PER_CONDITION,
                RUNS_DIR / "pilot",
                replace_failed_id=args.replace_failed,
            )
        else:
            mode_pilot()
    elif args.mode == "check":
        mode_check()
    elif args.mode == "main":
        if args.replace_failed:
            out = assert_main_run_not_completed(
                RUNS_DIR / "main", allow_new=args.allow_new_main_run
            )
            run_episodes(
                "main",
                N_EPISODES_PER_CONDITION,
                out,
                replace_failed_id=args.replace_failed,
            )
        else:
            mode_main(allow_new_main_run=args.allow_new_main_run)
    elif args.mode == "extract":
        mode_extract()


if __name__ == "__main__":
    main()
