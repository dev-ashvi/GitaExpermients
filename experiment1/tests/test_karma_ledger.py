"""Karma ledger append-only / duplicate-turn tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.karma_ledger import DuplicateTurnError, KarmaLedger


def _event(turn: int) -> dict:
    return {
        "turn": turn,
        "episode_id": "test",
        "SAL": None,
        "FRU": None,
        "DIS": None,
        "MEM": None,
        "BUD": None,
        "actor_output_initial": "x",
    }


def test_duplicate_karma_ledger_turn_raises(tmp_path: Path):
    path = tmp_path / "ep.jsonl"
    ledger = KarmaLedger(path)
    ledger.append(_event(1))
    with pytest.raises(DuplicateTurnError):
        ledger.append(_event(1))


def test_raw_ledger_is_append_only(tmp_path: Path):
    path = tmp_path / "ep.jsonl"
    ledger = KarmaLedger(path)
    ledger.append(_event(1))
    ledger.append(_event(2))
    # Re-open must not wipe
    ledger2 = KarmaLedger(path, create_new=True)
    assert ledger2.turn_count() == 2
    events = ledger2.load_all()
    assert [e["turn"] for e in events] == [1, 2]


def test_metrics_must_be_null_at_runtime(tmp_path: Path):
    path = tmp_path / "ep.jsonl"
    ledger = KarmaLedger(path)
    bad = _event(1)
    bad["SAL"] = 0.5
    with pytest.raises(ValueError):
        ledger.append(bad)
