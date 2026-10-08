"""Process-wide NVIDIA NIM HTTP start-to-start pacing (Experiment 0 engineering).

Enforced at the shared transport layer so Actor, Witness, revisions, token-count
probes, and retries cannot bypass the interval. Scientific protocol is unchanged.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional, Protocol


class PacingError(RuntimeError):
    """Fail-closed pacing / timing integrity failure."""


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def wall_unix(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall_unix(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class FakeClock:
    """Deterministic clock for tests (advance manually or via sleep)."""

    def __init__(self, *, mono: float = 1000.0, wall: float = 1_700_000_000.0):
        self._mono = float(mono)
        self._wall = float(wall)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._mono

    def wall_unix(self) -> float:
        return self._wall

    def sleep(self, seconds: float) -> None:
        sec = float(seconds)
        self.sleeps.append(sec)
        if sec > 0:
            self._mono += sec
            self._wall += sec

    def advance(self, seconds: float) -> None:
        self.sleep(seconds)


def _utc_from_unix(unix: float) -> str:
    return datetime.fromtimestamp(unix, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


@dataclass
class AttemptRecord:
    attempt_index: int
    role: str
    purpose: str
    scheduled_wait_sec: float
    actual_start_unix: float
    actual_start_utc: str
    actual_start_mono: float
    inter_start_interval_sec: Optional[float]
    duration_sec: Optional[float]
    http_status: Optional[int]
    ok: Optional[bool]
    error_class: Optional[str]


class GlobalHttpPacer:
    """Serialize NIM HTTP attempts and enforce min start-to-start interval.

    In-process spacing uses a monotonic clock. Cross-restart spacing uses
    persisted wall-clock start times. Concurrent callers block on a lock so at
    most one HTTP attempt is in flight.
    """

    def __init__(
        self,
        *,
        state_path: Path,
        attempt_log_path: Optional[Path] = None,
        min_interval_sec: float = 60.0,
        clock: Optional[Clock] = None,
        enabled: bool = True,
        require_readable_state_if_present: bool = True,
    ):
        self.state_path = Path(state_path)
        self.attempt_log_path = (
            Path(attempt_log_path) if attempt_log_path is not None else None
        )
        self.min_interval_sec = float(min_interval_sec)
        self.clock: Clock = clock or RealClock()
        self.enabled = bool(enabled)
        self.require_readable_state_if_present = require_readable_state_if_present
        self._lock = threading.RLock()
        self._last_start_mono: Optional[float] = None
        self._last_start_unix: Optional[float] = None
        self._attempt_index = 0
        self._inflight = False
        self.records: list[dict[str, Any]] = []
        # Load persisted wall start so restart cannot bypass pacing.
        self._bootstrap_from_disk()

    def _bootstrap_from_disk(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            if self.require_readable_state_if_present:
                raise PacingError(
                    f"NIM HTTP pacing state unreadable at {self.state_path}: {exc} "
                    "— fail closed (cannot establish prior attempt timing)"
                ) from exc
            return
        if not isinstance(data, dict):
            raise PacingError(
                f"NIM HTTP pacing state malformed at {self.state_path} — fail closed"
            )
        last = data.get("last_attempt_start_unix")
        if last is None:
            raise PacingError(
                "NIM HTTP pacing state missing last_attempt_start_unix — fail closed"
            )
        try:
            self._last_start_unix = float(last)
        except (TypeError, ValueError) as exc:
            raise PacingError(
                "NIM HTTP pacing state has invalid last_attempt_start_unix — fail closed"
            ) from exc
        if self._last_start_unix > self.clock.wall_unix() + 1.0:
            raise PacingError(
                "NIM HTTP pacing state is in the future relative to wall clock "
                "(clock skew / tamper) — fail closed"
            )
        idx = data.get("attempt_index")
        if idx is not None:
            self._attempt_index = int(idx)

    def _persist(self, *, start_unix: float, start_utc: str, meta: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1",
            "min_interval_sec": self.min_interval_sec,
            "last_attempt_start_unix": start_unix,
            "last_attempt_start_utc": start_utc,
            "attempt_index": self._attempt_index,
            "updated_utc": _utc_from_unix(self.clock.wall_unix()),
            "last_meta": meta,
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def _append_log(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        if self.attempt_log_path is None:
            return
        self.attempt_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.attempt_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _wait_for_slot(self) -> tuple[float, Optional[float]]:
        """Return (waited_sec, inter_start_interval_after_wait_or_None)."""
        if not self.enabled or self.min_interval_sec <= 0:
            return 0.0, None

        waited = 0.0
        # Prefer monotonic when available in this process.
        if self._last_start_mono is not None:
            elapsed = self.clock.monotonic() - self._last_start_mono
            need = self.min_interval_sec - elapsed
            if need > 0:
                self.clock.sleep(need)
                waited += need
        elif self._last_start_unix is not None:
            elapsed = self.clock.wall_unix() - self._last_start_unix
            if elapsed < 0:
                raise PacingError(
                    "Wall clock moved backwards relative to last NIM HTTP start "
                    "— fail closed"
                )
            need = self.min_interval_sec - elapsed
            if need > 0:
                self.clock.sleep(need)
                waited += need

        inter: Optional[float] = None
        if self._last_start_mono is not None:
            inter = self.clock.monotonic() - self._last_start_mono
        elif self._last_start_unix is not None:
            inter = self.clock.wall_unix() - self._last_start_unix
        return waited, inter

    @contextmanager
    def gated_attempt(
        self,
        *,
        role: str = "unknown",
        purpose: str = "",
    ) -> Generator[dict[str, Any], None, None]:
        """Hold exclusive access for one HTTP attempt; enforce start-to-start pacing.

        Yields a mutable attempt dict. Caller must set http_status / ok / error_class
        before exit when known. Does not store message bodies (Actor/Witness content).
        """
        self._lock.acquire()
        started = False
        record: dict[str, Any] = {
            "role": role,
            "purpose": purpose,
        }
        try:
            if self._inflight:
                # Should be impossible with the same lock; defend anyway.
                raise PacingError(
                    "Concurrent NIM HTTP attempt detected — fail closed"
                )
            waited, inter = self._wait_for_slot()
            start_mono = self.clock.monotonic()
            start_unix = self.clock.wall_unix()
            start_utc = _utc_from_unix(start_unix)
            self._attempt_index += 1
            self._inflight = True
            started = True
            self._last_start_mono = start_mono
            self._last_start_unix = start_unix
            meta = {
                "role": role,
                "purpose": purpose,
                # Never include prompt/response bodies.
            }
            self._persist(start_unix=start_unix, start_utc=start_utc, meta=meta)
            record.update(
                {
                    "attempt_index": self._attempt_index,
                    "scheduled_wait_sec": round(waited, 6),
                    "actual_start_unix": start_unix,
                    "actual_start_utc": start_utc,
                    "actual_start_mono": start_mono,
                    "inter_start_interval_sec": (
                        round(inter, 6) if inter is not None else None
                    ),
                    "duration_sec": None,
                    "http_status": None,
                    "ok": None,
                    "error_class": None,
                }
            )
            yield record
        finally:
            if started:
                end_mono = self.clock.monotonic()
                if record.get("actual_start_mono") is not None:
                    record["duration_sec"] = round(
                        end_mono - float(record["actual_start_mono"]), 6
                    )
                self._append_log(dict(record))
                self._inflight = False
            self._lock.release()
