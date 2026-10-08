"""PATCH 2 — fail-and-restart; no unsafe resume; main-run guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from main import assert_main_run_not_completed, write_main_run_manifest
from src.episode_runner import make_episode_id, make_replacement_episode_id
from src.karma_ledger import KarmaLedger


def test_failed_episode_ledger_never_overwritten(tmp_path: Path):
    path = tmp_path / "pilot_1_11111_abcd.jsonl"
    ledger = KarmaLedger(path)
    ledger.append({"turn": 1, "SAL": None, "FRU": None, "DIS": None, "MEM": None, "BUD": None})
    original = path.read_text(encoding="utf-8")
    # Simulate fail marker without truncating ledger
    fail = tmp_path / "pilot_1_11111_abcd.FAILED.json"
    fail.write_text(json.dumps({"status": "failed", "episode_id": path.stem}), encoding="utf-8")
    assert path.read_text(encoding="utf-8") == original


def test_replacement_episode_receives_new_id_and_references_failed():
    failed = "main_1_12345_deadbeef"
    new_id = make_replacement_episode_id("main", 1, 12345, failed)
    assert new_id != failed
    assert "repl" in new_id
    assert make_episode_id("main", 1, 12345) != new_id


def test_replacement_metadata_references_failed(tmp_path: Path):
    failed = "main_2_22222_fail0001"
    (tmp_path / f"{failed}.FAILED.json").write_text(
        json.dumps({"status": "failed", "episode_id": failed}), encoding="utf-8"
    )
    new_id = make_replacement_episode_id("main", 2, 22222, failed)
    meta = {
        "replacement_attempt": True,
        "episode_id": new_id,
        "replaces_episode_id": failed,
    }
    (tmp_path / f"{new_id}.REPLACEMENT.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    loaded = json.loads((tmp_path / f"{new_id}.REPLACEMENT.json").read_text(encoding="utf-8"))
    assert loaded["replaces_episode_id"] == failed
    assert loaded["episode_id"] != failed


def test_completed_main_run_prevents_accidental_rerun(tmp_path: Path):
    main_dir = tmp_path / "main"
    main_dir.mkdir()
    write_main_run_manifest(main_dir, status="completed", episodes_written=150)
    with pytest.raises(RuntimeError, match="Completed main run"):
        assert_main_run_not_completed(main_dir, allow_new=False)


def test_allow_new_main_run_creates_separate_directory(tmp_path: Path):
    main_dir = tmp_path / "main"
    main_dir.mkdir()
    write_main_run_manifest(main_dir, status="completed")
    new_dir = assert_main_run_not_completed(main_dir, allow_new=True)
    assert new_dir != main_dir
    assert new_dir.exists()
    assert new_dir.name.startswith("main_run_")
    # Original manifest untouched
    data = json.loads((main_dir / "main_run_manifest.json").read_text(encoding="utf-8"))
    assert data["status"] == "completed"


def test_no_raw_ledger_reused_across_separate_runs(tmp_path: Path):
    run_a = tmp_path / "main"
    run_a.mkdir()
    write_main_run_manifest(run_a, status="completed")
    ledger_a = run_a / "main_1_10000_aaaa.jsonl"
    KarmaLedger(ledger_a).append(
        {"turn": 1, "SAL": None, "FRU": None, "DIS": None, "MEM": None, "BUD": None}
    )
    run_b = assert_main_run_not_completed(run_a, allow_new=True)
    assert ledger_a.exists()
    assert not (run_b / ledger_a.name).exists()
