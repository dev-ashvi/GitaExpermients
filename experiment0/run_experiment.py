#!/usr/bin/env python3
"""Experiment 0 data-collection entrypoint.

Operational monitoring only during collection — no condition-separated science.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.capacity import run_capacity_preflight
from experiment0.episode_runner import (
    EpisodeFailedError,
    Experiment0EpisodeRunner,
    UnsafeResumeError,
    make_episode_id,
)
from experiment0.providers.base import ProviderError
from experiment0.providers.nim_provider import NimAnthropicCompatClient, NimChatProvider
from experiment0.script_loader import Experiment0ScriptLoader
from src.actor import Actor, build_actor_system_prompt, validate_actor_system_prompt
from src.buddhi import Buddhi
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.types_util import (
    assert_sources_not_placeholders,
    build_source_packet,
    load_text,
    sha256_file,
    sha256_text,
    validate_input_integrity,
)
from src.witness import Witness

e0 = load_experiment0_config()

RUN_MANIFEST_NAME = "run_manifest.json"
ASSIGNMENT_NAME = "assignment_schedule.json"
PROGRESS_NAME = "operational_progress.json"
OPS_LOG_NAME = "operational_log.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256_path(path: Path) -> str:
    return sha256_file(path)


def _redact_secrets(text: str) -> str:
    """Strip nvapi- credential material from any diagnostic string."""
    out = text
    marker = "nvapi-"
    while marker in out:
        i = out.index(marker)
        j = i + len(marker)
        while j < len(out) and out[j] not in " \n\r\t\"'":
            j += 1
        out = out[:i] + "nvapi-[REDACTED]" + out[j:]
    return out


def pre_execution_integrity() -> dict[str, Any]:
    """Hard stop checks before Episode 1. No auto-repair."""
    failures: list[str] = []
    report: dict[str, Any] = {"gate": "pre_execution_integrity"}

    # Config frozen params
    if e0.MAX_TOKENS_WITNESS != 1600:
        failures.append(f"MAX_TOKENS_WITNESS={e0.MAX_TOKENS_WITNESS} != 1600")
    if e0.MAX_TOKENS_ACTOR != 800:
        failures.append(f"MAX_TOKENS_ACTOR={e0.MAX_TOKENS_ACTOR} != 800")
    if e0.N_EPISODES_PER_CONDITION != 30 or e0.TOTAL_EPISODES != 60:
        failures.append(f"N mismatch: per={e0.N_EPISODES_PER_CONDITION} total={e0.TOTAL_EPISODES}")
    if tuple(e0.CONDITIONS) != (1, 2):
        failures.append(f"CONDITIONS={e0.CONDITIONS}")
    if e0.ENABLE_THINKING is not False:
        failures.append("ENABLE_THINKING must be False")
    if e0.ACTOR_MODEL != "nvidia/nemotron-3-super-120b-a12b":
        failures.append(f"ACTOR_MODEL={e0.ACTOR_MODEL}")
    if e0.WITNESS_MODEL != e0.ACTOR_MODEL:
        failures.append("WITNESS_MODEL mismatch")

    # Exp1 critical hashes
    critical = {
        "config/experiment_config.py": "14d42aa2288dd691ab511e76bca7c0f134d5b46d32cb7f5571c4273d903d50ac",
        "main.py": "7c17823717e1936975d783ff0431734f6da33875ea7336a3d559dbaf4d7cc3f6",
        "src/actor.py": "d0ed9dd1dd26b84973275f51a1ab49c8bdb499b599130627c6c5b78e62badbb6",
        "src/witness.py": "644daf98c82f070b5f389da09de704eca01c6b2c0e79d21cffa78b94f372590f",
        "src/episode_runner.py": "078fdb1aa19e1a34582be4469aded1465ba3f9ebc3604591774d7fb20abd7cf2",
        "src/buddhi.py": "56b06f535aa670069ae0473d9c9abb13244f2842978ee3a4b6df6e49ea5b4821",
        "src/script_loader.py": "c54f99926671a21df2072beb653d66a7b5c5298fd38040abab6547fdfe5bbd3d",
        "OPEN_ISSUES.md": "b887e90ce8876a621e19c7275de42191bd56fb83bc593ce3883349de6abc4dd1",
    }
    hash_ok = True
    for rel, expected in critical.items():
        actual = _sha256_path(EXP1 / rel)
        if actual != expected:
            hash_ok = False
            failures.append(f"Exp1 hash changed: {rel}")
    report["exp1_critical_hashes_ok"] = hash_ok

    try:
        verified = validate_input_integrity()
        report["frozen_manifest"] = f"{len(verified)}/{len(verified)}"
        if len(verified) != 14:
            failures.append(f"FROZEN_MANIFEST count {len(verified)}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"FROZEN_MANIFEST: {exc}")

    try:
        assert_sources_not_placeholders()
        report["s1_s5_ok"] = True
    except Exception as exc:  # noqa: BLE001
        failures.append(f"S1-S5: {exc}")
        report["s1_s5_ok"] = False

    # No prior episode ledger (exclude calibration)
    prior = []
    if e0.RUNS_DIR.exists():
        for p in e0.RUNS_DIR.rglob("*.jsonl"):
            if "calibration" in str(p).replace("\\", "/").lower():
                continue
            prior.append(str(p.relative_to(REPO)))
        for p in e0.RUNS_DIR.rglob("assignment_schedule.json"):
            prior.append(str(p.relative_to(REPO)))
        for p in e0.RUNS_DIR.rglob("run_manifest.json"):
            # allow only if we're resuming — checked by caller
            pass
    report["prior_episode_artifacts"] = prior

    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    sources = build_source_packet(e0.SOURCES_DIR)
    try:
        prompt = build_actor_system_prompt(
            constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
        )
        validate_actor_system_prompt(prompt)
        report["actor_isolation"] = "PASS"
    except Exception as exc:  # noqa: BLE001
        failures.append(f"actor_isolation: {exc}")
        report["actor_isolation"] = "FAIL"

    report["failures"] = failures
    report["ok"] = len(failures) == 0
    return report


def create_assignment_schedule(path: Path, *, master_seed: int) -> dict[str, Any]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        # Immutable once written
        return data

    rng = random.Random(master_seed)
    slots: list[dict[str, Any]] = []
    for cond in (1, 2):
        for i in range(e0.N_EPISODES_PER_CONDITION):
            slots.append(
                {
                    "condition": cond,
                    "seed": rng.randint(10000, 99999),
                    "slot_within_condition": i,
                }
            )
    rng.shuffle(slots)
    for idx, slot in enumerate(slots):
        slot["schedule_index"] = idx
        slot["episode_id"] = None  # filled at first attempt; persisted on assign

    data = {
        "description": (
            "Experiment 0 immutable condition assignment schedule. "
            "Randomized order of exactly 30 C1 + 30 C2. "
            "Seeds are assignment/audit only; they do NOT control NIM sampling."
        ),
        "master_seed": master_seed,
        "randomization": "random.Random(master_seed).shuffle over 30 C1 + 30 C2 slots",
        "n_c1": 30,
        "n_c2": 30,
        "n_total": 60,
        "created_utc": _utc_now(),
        "immutable": True,
        "slots": slots,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def bind_episode_ids(schedule: dict[str, Any], path: Path, run_id: str) -> dict[str, Any]:
    """Assign episode IDs once; never change after first bind."""
    changed = False
    for slot in schedule["slots"]:
        if not slot.get("episode_id"):
            slot["episode_id"] = make_episode_id(
                run_id=run_id,
                condition=int(slot["condition"]),
                seed=int(slot["seed"]),
                schedule_index=int(slot["schedule_index"]),
            )
            changed = True
    if changed:
        path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")
    return schedule


def build_run_manifest(run_dir: Path, run_id: str, schedule: dict[str, Any]) -> dict[str, Any]:
    input_hashes = validate_input_integrity()
    constitution_hash = _sha256_path(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    witness_protocol_hash = _sha256_path(e0.DOCUMENTS_DIR / "witness_protocol_v1.md")
    script_hash = _sha256_path(EXP1 / "data" / "documents" / "conversation_script_v1.md")
    config_hash = _sha256_path(REPO / "config" / "experiment0_config.py")
    script_loader_hash = _sha256_path(REPO / "experiment0" / "script_loader.py")
    source_hashes = {
        k: v for k, v in input_hashes.items() if k.startswith("S") and k.endswith(".txt")
    }
    manifest = {
        "run_id": run_id,
        "experiment_id": e0.EXPERIMENT_ID,
        "created_utc": _utc_now(),
        "status": "INITIALIZED",
        "provider": "nvidia-nim",
        "base_url": e0.NIM_BASE_URL,
        "actor_model": e0.ACTOR_MODEL,
        "witness_model": e0.WITNESS_MODEL,
        "actor_parameters": {
            "temperature": e0.ACTOR_TEMPERATURE,
            "max_tokens": e0.MAX_TOKENS_ACTOR,
            "enable_thinking": e0.ENABLE_THINKING,
            "top_p_sent": e0.SEND_TOP_P,
            "sampling_seed_sent": e0.SEND_SAMPLING_SEED,
        },
        "witness_parameters": {
            "temperature": e0.WITNESS_TEMPERATURE,
            "max_tokens": e0.MAX_TOKENS_WITNESS,
            "enable_thinking": e0.ENABLE_THINKING,
            "top_p_sent": e0.SEND_TOP_P,
            "sampling_seed_sent": e0.SEND_SAMPLING_SEED,
        },
        "n_episodes_per_condition": e0.N_EPISODES_PER_CONDITION,
        "n_total": e0.TOTAL_EPISODES,
        "conditions": list(e0.CONDITIONS),
        "assignment_master_seed": e0.ASSIGNMENT_MASTER_SEED,
        "assignment_schedule_hash": sha256_text(
            json.dumps(schedule, sort_keys=True, ensure_ascii=False)
        ),
        "config_hash": config_hash,
        "script_loader_hash": script_loader_hash,
        "source_manifest_hash": sha256_text(
            json.dumps(input_hashes, sort_keys=True)
        ),
        "input_hashes": input_hashes,
        "constitution_hash": constitution_hash,
        "witness_protocol_hash": witness_protocol_hash,
        "script_hash": script_hash,
        "source_hashes": source_hashes,
        "instrumentation_amendments": [
            "docs/experiment0_instrumentation_amendment_v1.0.1.md",
            "docs/experiment0_opposite_direction_clarification_v1.0.2.md",
        ],
        "capacity_fraction": e0.CONTEXT_CAPACITY_FRACTION,
        "model_context_limit": e0.MODEL_CONTEXT_LIMIT,
    }
    (run_dir / RUN_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def append_ops(run_dir: Path, record: dict[str, Any]) -> None:
    record = dict(record)
    record["timestamp_utc"] = _utc_now()
    line = _redact_secrets(json.dumps(record, ensure_ascii=False))
    with (run_dir / OPS_LOG_NAME).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_progress(run_dir: Path, **kwargs: Any) -> None:
    """Operational progress only — no condition-separated scientific metrics."""
    allowed = {
        "episodes_attempted",
        "episodes_completed",
        "episodes_failed_operational",
        "provider_failures",
        "retries_total",
        "last_episode_id",
        "last_schedule_index",
        "status",
        "elapsed_sec",
        "note",
    }
    payload = {k: v for k, v in kwargs.items() if k in allowed}
    payload["updated_utc"] = _utc_now()
    (run_dir / PROGRESS_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def episode_complete(ledger_path: Path) -> bool:
    if not ledger_path.exists():
        return False
    events = KarmaLedger.read_file(ledger_path)
    turns = {e.get("turn") for e in events}
    return turns == set(range(1, e0.TOTAL_TURNS + 1))


def run_one_episode(
    *,
    run_dir: Path,
    run_id: str,
    slot: dict[str, Any],
    manifest: dict[str, Any],
    provider: NimChatProvider,
) -> dict[str, Any]:
    condition = int(slot["condition"])
    seed = int(slot["seed"])
    schedule_index = int(slot["schedule_index"])
    episode_id = str(slot["episode_id"])
    ledger_path = run_dir / "episodes" / f"{episode_id}.jsonl"

    if episode_complete(ledger_path):
        return {"status": "already_complete", "episode_id": episode_id}

    if ledger_path.exists() and not episode_complete(ledger_path):
        # Fail-and-restart: quarantine partial, new attempt keeps same schedule slot
        # but must not duplicate under same ledger — quarantine and recreate
        quarantine = ledger_path.with_suffix(
            f".partial_{int(time.time())}.jsonl.bak"
        )
        ledger_path.rename(quarantine)
        append_ops(
            run_dir,
            {
                "event": "partial_quarantined",
                "episode_id": episode_id,
                "quarantine": str(quarantine.name),
            },
        )

    sources = build_source_packet(e0.SOURCES_DIR)
    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    system_prompt = build_actor_system_prompt(
        constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
    )

    actor_client = NimAnthropicCompatClient(provider, enable_thinking=e0.ENABLE_THINKING)
    witness_client = NimAnthropicCompatClient(provider, enable_thinking=e0.ENABLE_THINKING)

    actor = Actor(
        actor_client,
        system_prompt,
        model=e0.ACTOR_MODEL,
        temperature=e0.ACTOR_TEMPERATURE,
        max_tokens=e0.MAX_TOKENS_ACTOR,
    )
    witness = Witness(
        witness_client,
        load_text(e0.DOCUMENTS_DIR / "witness_protocol_v1.md"),
        sources,
        model=e0.WITNESS_MODEL,
        temperature=e0.WITNESS_TEMPERATURE,
        max_tokens=e0.MAX_TOKENS_WITNESS,
    )
    ledger = KarmaLedger(ledger_path, create_new=True)
    runner = Experiment0EpisodeRunner(
        actor,
        witness,
        Buddhi(),
        OSM(),
        Experiment0ScriptLoader(),
        ledger,
        condition=condition,
        seed=seed,
        episode_id=episode_id,
        run_id=run_id,
        input_hashes=manifest["input_hashes"],
        constitution_hash=manifest["constitution_hash"],
        witness_protocol_hash=manifest["witness_protocol_hash"],
        script_hash=manifest["script_hash"],
        source_hashes=manifest["source_hashes"],
        schedule_index=schedule_index,
    )
    t0 = time.time()
    try:
        runner.run()
        return {
            "status": "completed",
            "episode_id": episode_id,
            "elapsed_sec": round(time.time() - t0, 2),
        }
    except (EpisodeFailedError, ProviderError, UnsafeResumeError, Exception) as exc:
        return {
            "status": "failed",
            "episode_id": episode_id,
            "error": _redact_secrets(str(exc)),
            "elapsed_sec": round(time.time() - t0, 2),
            "traceback": _redact_secrets(traceback.format_exc()[-2000:]),
        }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment 0 data collection")
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Skip re-running pytest (only if already verified this session)",
    )
    parser.add_argument(
        "--resume-run-id",
        default="",
        help="Resume an existing run_id directory under experiment0/runs/",
    )
    args = parser.parse_args(argv)

    print("=== Experiment 0 pre-execution integrity ===", flush=True)
    if not args.skip_pytest:
        import subprocess

        r0 = subprocess.run(
            [sys.executable, "-m", "pytest", "experiment0/tests", "-q", "--tb=line"],
            cwd=str(REPO),
        )
        r1 = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "--tb=line"],
            cwd=str(EXP1),
        )
        if r0.returncode != 0 or r1.returncode != 0:
            print("RUN_BLOCKED_PRE_EXECUTION_INTEGRITY", flush=True)
            print(f"pytest_exp0={r0.returncode} pytest_exp1={r1.returncode}", flush=True)
            return 2
        print("pytest: Experiment0=PASS Experiment1=PASS (expect 30+113)", flush=True)

    gate = pre_execution_integrity()
    if args.resume_run_id:
        # Resuming: prior schedule/manifest expected
        run_dir = e0.RUNS_DIR / args.resume_run_id
        if not (run_dir / RUN_MANIFEST_NAME).exists():
            print("RUN_BLOCKED_PRE_EXECUTION_INTEGRITY", flush=True)
            print("resume target missing run_manifest", flush=True)
            return 2
        gate["prior_episode_artifacts"] = []  # allowed when resuming
        # Re-check config/hashes still
        if not gate["ok"] and any(
            "prior" not in f for f in gate["failures"]
        ):
            # filter prior-artifact failures for resume
            gate["failures"] = [
                f
                for f in gate["failures"]
                if "prior" not in f.lower() and "assignment" not in f.lower()
            ]
            gate["ok"] = len(gate["failures"]) == 0
    else:
        if gate.get("prior_episode_artifacts"):
            # Only block if there are non-calibration episode jsonl outside a run we're resuming
            # Fresh start: any assignment_schedule or episode jsonl under runs (non-calibration) blocks
            print("RUN_BLOCKED_PRE_EXECUTION_INTEGRITY", flush=True)
            print("prior_episode_artifacts=", gate["prior_episode_artifacts"], flush=True)
            return 2

    if not gate["ok"]:
        print("RUN_BLOCKED_PRE_EXECUTION_INTEGRITY", flush=True)
        print(json.dumps(gate, indent=2), flush=True)
        return 2
    print("pre_execution_integrity: PASS", flush=True)

    if not os.environ.get(e0.NIM_API_KEY_ENV, "").strip():
        print("RUN_BLOCKED_PRE_EXECUTION_INTEGRITY", flush=True)
        print(f"{e0.NIM_API_KEY_ENV} is not set in the environment.", flush=True)
        return 2

    print("=== Capacity preflight (provider-exact) ===", flush=True)
    provider = NimChatProvider(
        api_key_env=e0.NIM_API_KEY_ENV,
        base_url=e0.NIM_BASE_URL,
        max_retries=e0.API_MAX_RETRIES,
        retry_base_delay_sec=e0.API_RETRY_BASE_DELAY_SEC,
        send_top_p=e0.SEND_TOP_P,
        send_sampling_seed=e0.SEND_SAMPLING_SEED,
    )
    try:
        capacity = run_capacity_preflight(provider)
    except Exception as exc:  # noqa: BLE001
        print("RUN_BLOCKED_CAPACITY", flush=True)
        print(_redact_secrets(str(exc)), flush=True)
        return 3
    print(
        json.dumps(
            {
                "actor": capacity["actor"],
                "witness": capacity["witness"],
                "ok": capacity["ok"],
            },
            indent=2,
        ),
        flush=True,
    )
    if not capacity["ok"]:
        print("RUN_BLOCKED_CAPACITY", flush=True)
        return 3

    # Run identity
    if args.resume_run_id:
        run_id = args.resume_run_id
        run_dir = e0.RUNS_DIR / run_id
        manifest = json.loads((run_dir / RUN_MANIFEST_NAME).read_text(encoding="utf-8"))
        schedule = json.loads((run_dir / ASSIGNMENT_NAME).read_text(encoding="utf-8"))
        print(f"Resuming run_id={run_id}", flush=True)
    else:
        run_id = datetime.now(timezone.utc).strftime("e0_%Y%m%dT%H%M%SZ")
        run_dir = e0.RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "episodes").mkdir(parents=True, exist_ok=True)
        schedule = create_assignment_schedule(
            run_dir / ASSIGNMENT_NAME, master_seed=e0.ASSIGNMENT_MASTER_SEED
        )
        schedule = bind_episode_ids(schedule, run_dir / ASSIGNMENT_NAME, run_id)
        manifest = build_run_manifest(run_dir, run_id, schedule)
        manifest["capacity_preflight"] = capacity
        manifest["status"] = "RUNNING"
        manifest["started_utc"] = _utc_now()
        (run_dir / RUN_MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        print(f"Created run_id={run_id}", flush=True)

    append_ops(run_dir, {"event": "collection_start", "run_id": run_id})

    completed = 0
    attempted = 0
    failed_ops = 0
    provider_failures = 0
    t_start = time.time()

    for slot in schedule["slots"]:
        eid = slot["episode_id"]
        ledger_path = run_dir / "episodes" / f"{eid}.jsonl"
        if episode_complete(ledger_path):
            completed += 1
            continue

        attempted += 1
        write_progress(
            run_dir,
            episodes_attempted=attempted,
            episodes_completed=completed,
            episodes_failed_operational=failed_ops,
            provider_failures=provider_failures,
            last_episode_id=eid,
            last_schedule_index=slot["schedule_index"],
            status="RUNNING",
            elapsed_sec=round(time.time() - t_start, 1),
            note="operational_only_no_scientific_metrics",
        )
        append_ops(
            run_dir,
            {
                "event": "episode_start",
                "schedule_index": slot["schedule_index"],
                "episode_id": eid,
                # condition logged for ops resume identity only — not outcome metrics
                "condition": slot["condition"],
            },
        )
        print(
            f"[ops] start schedule_index={slot['schedule_index']} episode={eid}",
            flush=True,
        )
        result = run_one_episode(
            run_dir=run_dir,
            run_id=run_id,
            slot=slot,
            manifest=manifest,
            provider=provider,
        )
        append_ops(run_dir, {"event": "episode_result", **result})
        if result["status"] in ("completed", "already_complete"):
            completed += 1
            print(
                f"[ops] done schedule_index={slot['schedule_index']} "
                f"elapsed={result.get('elapsed_sec')} completed={completed}/60",
                flush=True,
            )
        else:
            failed_ops += 1
            provider_failures += 1
            print(
                f"[ops] FAIL schedule_index={slot['schedule_index']} "
                f"error={result.get('error')}",
                flush=True,
            )
            # Freeze run for review — do not invent new assignment
            manifest["status"] = "STOPPED_FOR_REVIEW"
            manifest["stop_reason"] = result.get("error")
            manifest["stopped_utc"] = _utc_now()
            (run_dir / RUN_MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            write_progress(
                run_dir,
                episodes_attempted=attempted,
                episodes_completed=completed,
                episodes_failed_operational=failed_ops,
                provider_failures=provider_failures,
                last_episode_id=eid,
                last_schedule_index=slot["schedule_index"],
                status="STOPPED_FOR_REVIEW",
                elapsed_sec=round(time.time() - t_start, 1),
            )
            print("RUN_STOPPED_FOR_REVIEW — frozen assignment preserved", flush=True)
            return 4

    # All 60 complete — freeze raw dataset
    manifest["status"] = "RAW_DATASET_FROZEN"
    manifest["completed_utc"] = _utc_now()
    manifest["episodes_completed"] = completed
    # Count conditions without computing science
    c1 = sum(1 for s in schedule["slots"] if s["condition"] == 1)
    c2 = sum(1 for s in schedule["slots"] if s["condition"] == 2)
    manifest["condition_allocation"] = {"C1": c1, "C2": c2}
    # Dataset hash over all episode ledgers in schedule order
    h = hashlib.sha256()
    for slot in schedule["slots"]:
        p = run_dir / "episodes" / f"{slot['episode_id']}.jsonl"
        h.update(p.read_bytes())
    manifest["raw_dataset_hash"] = h.hexdigest()
    (run_dir / RUN_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    write_progress(
        run_dir,
        episodes_attempted=attempted,
        episodes_completed=completed,
        episodes_failed_operational=failed_ops,
        provider_failures=provider_failures,
        status="RAW_DATASET_FROZEN",
        elapsed_sec=round(time.time() - t_start, 1),
    )
    append_ops(run_dir, {"event": "raw_dataset_frozen", "dataset_hash": manifest["raw_dataset_hash"]})
    print(f"RAW_DATASET_FROZEN run_id={run_id} hash={manifest['raw_dataset_hash']}", flush=True)
    print(f"RUN_DIR={run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
