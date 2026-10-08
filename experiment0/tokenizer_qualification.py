"""Provider-bound qualification evidence for local Nemotron token counting.

A local counter must NOT report VERIFIED unless an explicitly validated
evidence record authorizes the active provider profile. Presence of a report
markdown file alone is insufficient.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PINNING_MANIFEST = (
    REPO_ROOT
    / "experiment0"
    / "tokenizers"
    / "nemotron3_super_120b_bf16"
    / "PINNING_MANIFEST.json"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "experiment0"
    / "tokenizers"
    / "nemotron3_super_120b_bf16"
    / "QUALIFICATION_EVIDENCE.json"
)

REQUIRED_EVIDENCE_FIELDS = (
    "schema_version",
    "model_id",
    "provider_profile",
    "tokenizer_repo",
    "tokenizer_revision",
    "artifact_hashes",
    "chat_template_sha256",
    "serialization_params",
    "hosted_qualification_status",
    "evidence_validated",
    "validated_utc",
    "validator_id",
    "probe_results",
)


class QualificationError(RuntimeError):
    """Evidence missing, incomplete, or not explicitly validated."""


@dataclass(frozen=True)
class TokenizerQualificationEvidence:
    model_id: str
    provider_profile: str
    tokenizer_repo: str
    tokenizer_revision: str
    artifact_hashes: dict[str, str]
    chat_template_sha256: str
    serialization_params: dict[str, Any]
    hosted_qualification_status: str
    evidence_validated: bool
    validated_utc: str
    validator_id: str
    probe_results: list[dict[str, Any]]
    raw: dict[str, Any]

    def authorizes(
        self,
        *,
        provider_profile: str,
        model_id: str,
        pinning: dict[str, Any],
    ) -> bool:
        """Return True only when Stage-B-validated evidence matches pinned artifacts."""
        if not self.evidence_validated:
            return False
        if self.hosted_qualification_status != "PASSED":
            return False
        if self.provider_profile != provider_profile:
            return False
        if self.model_id != model_id:
            return False
        if self.tokenizer_repo != pinning.get("huggingface_repo"):
            return False
        if self.tokenizer_revision != pinning.get("huggingface_revision"):
            return False
        if self.chat_template_sha256 != pinning.get("chat_template_sha256"):
            return False
        pinned_files = pinning.get("files") or {}
        for name, meta in pinned_files.items():
            expected = (meta or {}).get("sha256")
            actual = self.artifact_hashes.get(name)
            if not expected or actual != expected:
                return False
        # Serialization params must match counting contract
        sp = self.serialization_params or {}
        pinned_sp = pinning.get("serialization_params_for_counting") or {}
        for k, v in pinned_sp.items():
            if sp.get(k) != v:
                return False
        # Probe results must exist and all pass with absolute zero delta
        if not self.probe_results:
            return False
        for pr in self.probe_results:
            if pr.get("delta") != 0:
                return False
            if pr.get("status") != "PASS":
                return False
        return True


def load_pinning_manifest(path: Optional[Path] = None) -> dict[str, Any]:
    p = Path(path) if path is not None else DEFAULT_PINNING_MANIFEST
    if not p.exists():
        raise QualificationError(f"Pinning manifest missing: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def verify_artifact_hashes(
    tokenizer_dir: Path, pinning: dict[str, Any]
) -> dict[str, str]:
    """Recompute on-disk SHA-256; raise if mismatch or missing."""
    files = pinning.get("files") or {}
    out: dict[str, str] = {}
    for name, meta in files.items():
        fp = tokenizer_dir / name
        if not fp.exists():
            raise QualificationError(f"Pinned tokenizer artifact missing: {fp}")
        digest = hashlib.sha256(fp.read_bytes()).hexdigest()
        expected = (meta or {}).get("sha256")
        if digest != expected:
            raise QualificationError(
                f"Tokenizer artifact hash mismatch for {name}: "
                f"on_disk={digest} pinned={expected}"
            )
        out[name] = digest
    return out


def load_qualification_evidence(
    path: Optional[Path] = None,
) -> Optional[TokenizerQualificationEvidence]:
    """Load evidence if present. Does not treat absence as error."""
    p = Path(path) if path is not None else DEFAULT_EVIDENCE_PATH
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_EVIDENCE_FIELDS if k not in raw]
    if missing:
        raise QualificationError(
            f"Qualification evidence incomplete; missing fields: {missing}"
        )
    return TokenizerQualificationEvidence(
        model_id=str(raw["model_id"]),
        provider_profile=str(raw["provider_profile"]),
        tokenizer_repo=str(raw["tokenizer_repo"]),
        tokenizer_revision=str(raw["tokenizer_revision"]),
        artifact_hashes=dict(raw["artifact_hashes"]),
        chat_template_sha256=str(raw["chat_template_sha256"]),
        serialization_params=dict(raw["serialization_params"]),
        hosted_qualification_status=str(raw["hosted_qualification_status"]),
        evidence_validated=bool(raw["evidence_validated"]),
        validated_utc=str(raw["validated_utc"]),
        validator_id=str(raw["validator_id"]),
        probe_results=list(raw["probe_results"]),
        raw=raw,
    )


def write_pending_evidence_stub(
    path: Optional[Path] = None,
    *,
    pinning: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create a non-authorizing PENDING stub for Stage B (never VERIFIED)."""
    pinning = pinning or load_pinning_manifest()
    artifact_hashes = {
        name: meta["sha256"] for name, meta in (pinning.get("files") or {}).items()
    }
    stub = {
        "schema_version": "1",
        "model_id": pinning.get("api_model_id", "nvidia/nemotron-3-super-120b-a12b"),
        "provider_profile": "nvidia-nim",
        "tokenizer_repo": pinning["huggingface_repo"],
        "tokenizer_revision": pinning["huggingface_revision"],
        "artifact_hashes": artifact_hashes,
        "chat_template_sha256": pinning["chat_template_sha256"],
        "serialization_params": dict(
            pinning.get("serialization_params_for_counting") or {}
        ),
        "hosted_qualification_status": "PENDING_STAGE_B",
        "evidence_validated": False,
        "validated_utc": "",
        "validator_id": "",
        "probe_results": [],
        "note": (
            "Stage A stub only. Does NOT authorize VERIFIED token counts. "
            "Stage B must set hosted_qualification_status=PASSED, "
            "evidence_validated=true, validator_id, validated_utc, and "
            "probe_results with delta==0 for every probe."
        ),
    }
    out = Path(path) if path is not None else DEFAULT_EVIDENCE_PATH
    out.write_text(json.dumps(stub, indent=2), encoding="utf-8")
    return stub
