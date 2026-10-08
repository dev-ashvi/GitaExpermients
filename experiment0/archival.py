"""Operational archival / exclusion guards for aborted Experiment 0 runs.

Additive only: does not overwrite or delete scientific ledgers, schedules,
hashes, or diagnostics. Does not inspect Actor/Witness scientific payloads.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from experiment0 import engineering_config as eng

ARCHIVAL_MANIFEST_NAME = eng.ARCHIVAL_MANIFEST_FILENAME
LABEL_ABORTED_PRE_ANALYSIS = eng.ARCHIVAL_LABEL_ABORTED_PRE_ANALYSIS


class ArchivedRunError(RuntimeError):
    """Fail-closed: archived / excluded run must not resume or enter clean analysis."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def archival_manifest_path(run_dir: Path) -> Path:
    return Path(run_dir) / ARCHIVAL_MANIFEST_NAME


def is_archived(run_dir: Path) -> bool:
    return archival_manifest_path(run_dir).exists()


def load_archival_manifest(run_dir: Path) -> Optional[dict[str, Any]]:
    path = archival_manifest_path(run_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def assert_not_archived_for_resume(run_dir: Path) -> None:
    man = load_archival_manifest(run_dir)
    if man is None:
        # Also honor engineering exclusion list even before manifest write
        run_id = Path(run_dir).name
        if run_id in eng.EXCLUDED_FROM_CLEAN_N60_RUN_IDS:
            raise ArchivedRunError(
                f"Run {run_id} is listed in EXCLUDED_FROM_CLEAN_N60_RUN_IDS — "
                "resume blocked (fail closed). Apply/consult ARCHIVAL_MANIFEST."
            )
        return
    raise ArchivedRunError(
        f"Run {Path(run_dir).name} is archived "
        f"({man.get('archival_label')}) — resume blocked (fail closed)."
    )


def assert_allowed_for_clean_analysis(run_dir: Path) -> None:
    """Block scientific analysis of archived / excluded incomplete runs."""
    run_id = Path(run_dir).name
    man = load_archival_manifest(run_dir)
    if man is not None:
        raise ArchivedRunError(
            f"Run {run_id} is archived ({man.get('archival_label')}) and "
            f"excluded_from_clean_n60={man.get('excluded_from_clean_n60')} — "
            "analysis of this run as clean N=60 primary data is forbidden."
        )
    if run_id in eng.EXCLUDED_FROM_CLEAN_N60_RUN_IDS:
        raise ArchivedRunError(
            f"Run {run_id} is listed in EXCLUDED_FROM_CLEAN_N60_RUN_IDS — "
            "clean-run analysis blocked (fail closed)."
        )


def write_aborted_operational_archival_record(
    run_dir: Path,
    *,
    run_id: str,
    completed_episodes: int,
    total_episodes: int,
    prior_status: str,
    stop_reason_ops: str,
    note: str = "",
) -> dict[str, Any]:
    """Create additive ARCHIVAL_MANIFEST.json. Does not rewrite ledgers/schedule."""
    run_dir = Path(run_dir)
    path = archival_manifest_path(run_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    # Inventory paths only — do not open episode ledgers for scientific fields.
    episodes_dir = run_dir / "episodes"
    episode_files = sorted(p.name for p in episodes_dir.glob("*.jsonl")) if episodes_dir.exists() else []
    partial_bak = (
        sorted(p.name for p in episodes_dir.glob("*.partial_*.jsonl.bak"))
        if episodes_dir.exists()
        else []
    )
    present = {
        "run_manifest.json": (run_dir / "run_manifest.json").exists(),
        "assignment_schedule.json": (run_dir / "assignment_schedule.json").exists(),
        "operational_progress.json": (run_dir / "operational_progress.json").exists(),
        "operational_log.jsonl": (run_dir / "operational_log.jsonl").exists(),
    }

    record: dict[str, Any] = {
        "archival_label": LABEL_ABORTED_PRE_ANALYSIS,
        "run_id": run_id,
        "archived_utc": _utc_now(),
        "prior_status": prior_status,
        "completed_episodes": completed_episodes,
        "total_episodes_planned": total_episodes,
        "excluded_from_clean_n60": True,
        "excluded_from_primary_dataset": True,
        "scientific_analysis_performed": False,
        "scientific_outcomes_inspected": False,
        "inspection_forbidden_fields": [
            "actor_output_initial",
            "actor_output_final",
            "witness_raw scores/verdict/reasoning",
            "witness_final scores/verdict/reasoning",
            "RCVR",
            "BUD",
            "AlignmentScore",
            "condition-wise scientific outcomes",
        ],
        "preserve": {
            "ledgers": True,
            "schedule": True,
            "hashes": True,
            "run_metadata": True,
            "diagnostics": True,
            "do_not_overwrite_or_delete": True,
            "do_not_regenerate_schedule": True,
        },
        "stop_reason_ops": stop_reason_ops,
        "artifact_inventory": {
            "present": present,
            "episode_jsonl_count": len(episode_files),
            "episode_jsonl_names": episode_files,
            "partial_quarantine_bak_names": partial_bak,
        },
        "guards": {
            "resume_blocked": True,
            "clean_n60_analysis_blocked": True,
            "replacement_schedule_not_created": True,
        },
        "note": note
        or (
            "Aborted for operational rate limits prior to analysis. "
            "Completed episodes are excluded from any future clean N=60 "
            "primary dataset. Additive archival only."
        ),
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
