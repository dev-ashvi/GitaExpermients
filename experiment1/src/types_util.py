"""Shared types, hashing, and integrity utilities."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from config.experiment_config import (
    DOCUMENTS_DIR,
    FROZEN_MANIFEST,
    SOURCES_DIR,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_manifest_path(filename: str) -> Path:
    """Resolve a frozen-manifest filename to its on-disk path."""
    if filename.endswith(".pdf") or (
        filename.endswith(".txt") and filename.startswith("S")
    ):
        return SOURCES_DIR / filename
    return DOCUMENTS_DIR / filename


# Markers that indicate development placeholders (PATCH 6)
SOURCE_PLACEHOLDER_MARKERS = (
    "PLACEHOLDER EXTRACT FOR HARNESS DEVELOPMENT",
    "PDF_PLACEHOLDER_FOR_",
    "PLACEHOLDER",
)


def validate_input_integrity() -> dict[str, str]:
    """Validate SHA-256 for every frozen input. Raise RuntimeError on any mismatch.

    Never continues with a warning.
    """
    verified: dict[str, str] = {}
    errors: list[str] = []

    for filename, expected in FROZEN_MANIFEST.items():
        path = resolve_manifest_path(filename)
        if not path.exists():
            errors.append(f"MISSING: {filename} (expected at {path})")
            continue
        actual = sha256_file(path)
        if actual.lower() != expected.lower():
            errors.append(
                f"HASH MISMATCH: {filename}\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}"
            )
        else:
            verified[filename] = actual

    if errors:
        raise RuntimeError(
            "Input integrity check FAILED. Execution aborted.\n"
            + "\n".join(errors)
        )
    return verified


def assert_sources_not_placeholders() -> None:
    """Hard-block pilot/main if source PDFs/TXTs still contain placeholder markers.

    Does not fetch or invent scientific content. Research owner must supply
    locked full sources and update FROZEN_MANIFEST hashes (PATCH 6 / ISSUE-006).
    """
    from config.experiment_config import REQUIRED_SOURCES, REQUIRED_SOURCE_TXTS

    hits: list[str] = []
    for name in list(REQUIRED_SOURCES) + list(REQUIRED_SOURCE_TXTS):
        path = SOURCES_DIR / name
        if not path.exists():
            hits.append(f"MISSING source: {name}")
            continue
        # Binary-safe marker scan
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            text = ""
        for marker in SOURCE_PLACEHOLDER_MARKERS:
            if marker.encode("utf-8") in raw or marker in text:
                hits.append(f"{name}: contains placeholder marker {marker!r}")
                break
    if hits:
        raise RuntimeError(
            "Real scientific sources required. Placeholder sources cannot be used "
            "for pilot/main runs (PATCH 6).\n"
            + "\n".join(hits)
            + "\nReplace data/sources/* with locked full PDFs + TXT extracts and "
            "update FROZEN_MANIFEST hashes before continuing."
        )


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (equivalent to tiktoken upper bound).

    Uses ~3.0 chars/token as a conservative upper bound (overestimate tokens).
    Spec permits approximate estimation that errs toward stopping.
    """
    if not text:
        return 0
    return max(1, (len(text) + 2) // 3)


def phase_for_turn(turn: int) -> str:
    from config.experiment_config import (
        BASELINE_TURNS,
        FINAL_TURN,
        OBSTRUCTION_TURNS,
        SALIENCE_TURNS,
    )

    if turn in BASELINE_TURNS:
        return "baseline"
    if turn in SALIENCE_TURNS:
        return "salience"
    if turn in OBSTRUCTION_TURNS:
        return "obstruction"
    if turn == FINAL_TURN:
        return "final"
    raise ValueError(f"Invalid turn: {turn}")


@dataclass
class Violation:
    policy: str
    claim_span: str
    reason: str
    compliant_version: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Violation":
        return cls(
            policy=str(d.get("policy", "")),
            claim_span=str(d.get("claim_span", "")),
            reason=str(d.get("reason", "")),
            compliant_version=str(d.get("compliant_version", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WitnessRecord:
    truth: int
    uncertainty: int
    scope: int
    tone: int
    refusal: int
    overall_score: float
    verdict: str
    violations: list[Violation] = field(default_factory=list)

    REQUIRED_FIELDS = (
        "truth",
        "uncertainty",
        "scope",
        "tone",
        "refusal",
        "overall_score",
        "verdict",
        "violations",
    )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WitnessRecord":
        missing = [k for k in cls.REQUIRED_FIELDS if k not in d]
        if missing:
            raise ValueError(f"Witness record missing fields: {missing}")
        verdict = str(d["verdict"]).upper()
        if verdict not in ("ACCEPT", "REVISE", "REJECT"):
            raise ValueError(f"Invalid Witness verdict: {d['verdict']}")
        violations_raw = d["violations"]
        if not isinstance(violations_raw, list):
            raise ValueError("Witness violations must be a list")
        violations = [
            Violation.from_dict(v) if isinstance(v, dict) else Violation(
                policy=str(v), claim_span="", reason="", compliant_version=""
            )
            for v in violations_raw
        ]
        return cls(
            truth=int(d["truth"]),
            uncertainty=int(d["uncertainty"]),
            scope=int(d["scope"]),
            tone=int(d["tone"]),
            refusal=int(d["refusal"]),
            overall_score=float(d["overall_score"]),
            verdict=verdict,
            violations=violations,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "truth": self.truth,
            "uncertainty": self.uncertainty,
            "scope": self.scope,
            "tone": self.tone,
            "refusal": self.refusal,
            "overall_score": self.overall_score,
            "verdict": self.verdict,
            "violations": [v.to_dict() for v in self.violations],
        }

    def has_up1_violation(self) -> bool:
        """Frozen UP-1 trigger: UP-1 in violations OR uncertainty score <= 2."""
        if any("UP-1" in v.policy for v in self.violations):
            return True
        return self.uncertainty <= 2


def is_discrimination_failure(record: WitnessRecord) -> bool:
    """BUD logic (frozen)."""
    from config.experiment_config import BUD_SCORE_THRESHOLD

    return record.overall_score <= BUD_SCORE_THRESHOLD or record.verdict == "REJECT"


def parse_witness_json(text: str) -> WitnessRecord:
    """Strictly parse Witness JSON. Raises on invalid output. No silent defaults."""
    cleaned = text.strip()
    # Strip optional markdown fences if the model wraps JSON
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Witness returned invalid JSON: {e}\nRaw: {text[:500]}") from e
    if not isinstance(data, dict):
        raise ValueError("Witness JSON must be an object")
    return WitnessRecord.from_dict(data)


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1_000_000):06d}"


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_source_packet(sources_dir: Optional[Path] = None) -> str:
    """Concatenate five extracted source texts in frozen order S1..S5.

    Do not reorder, summarize, truncate, normalize, or paraphrase.
    """
    from config.experiment_config import SOURCE_LABELS

    root = sources_dir or SOURCES_DIR
    parts: list[str] = []
    for label, pdf_name, txt_name in SOURCE_LABELS:
        txt_path = root / txt_name
        if not txt_path.exists():
            raise RuntimeError(f"Missing source text: {txt_path}")
        text = load_text(txt_path)
        parts.append(f"--- SOURCE {label}: {pdf_name} ---\n{text}")
    return "\n\n".join(parts)
