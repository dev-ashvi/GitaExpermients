"""Append-only Karma ledger — one JSONL file per episode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Optional, Set


class DuplicateTurnError(RuntimeError):
    """Raised when attempting to append a turn that already exists."""


class KarmaLedger:
    """Append-only JSONL logger. Never overwrites. Raises on duplicate turn."""

    def __init__(self, path: Path, *, create_new: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen_turns: Set[int] = set()

        if self.path.exists():
            if create_new:
                # Resumability: load existing turns; never truncate
                for event in self.iter_events():
                    turn = event.get("turn")
                    if isinstance(turn, int):
                        self._seen_turns.add(turn)
            else:
                raise RuntimeError(f"Ledger already exists: {self.path}")
        else:
            # Create empty file (append-only from first write)
            self.path.touch()

    def has_turn(self, turn: int) -> bool:
        return turn in self._seen_turns

    def append(self, event: dict[str, Any]) -> None:
        turn = event.get("turn")
        if not isinstance(turn, int):
            raise ValueError("Ledger event must include integer 'turn'")
        if turn in self._seen_turns:
            raise DuplicateTurnError(
                f"Duplicate turn {turn} in ledger {self.path}"
            )
        # Enforce runtime metrics null
        for key in ("SAL", "FRU", "DIS", "MEM", "BUD"):
            if key in event and event[key] is not None:
                raise ValueError(
                    f"Metric {key} must be null at runtime; got {event[key]!r}"
                )
            event[key] = None

        line = json.dumps(event, ensure_ascii=False, sort_keys=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
        self._seen_turns.add(turn)

    def iter_events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
            yield  # pragma: no cover
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    def load_all(self) -> list[dict[str, Any]]:
        return list(self.iter_events())

    def turn_count(self) -> int:
        return len(self._seen_turns)

    @staticmethod
    def read_file(path: Path) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        with Path(path).open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
