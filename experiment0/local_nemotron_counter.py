"""Offline Nemotron chat token counter (Stage A — UNVERIFIED until Stage B evidence).

Uses pinned HF tokenizer/template artifacts only. No model weights. No inference.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Optional

from experiment0.capacity_gate import TokenCountTrust
from experiment0.providers.message_assembly import assemble_openai_chat_messages
from experiment0.tokenizer_qualification import (
    DEFAULT_PINNING_MANIFEST,
    QualificationError,
    TokenizerQualificationEvidence,
    load_pinning_manifest,
    load_qualification_evidence,
    verify_artifact_hashes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOKENIZER_DIR = (
    REPO_ROOT / "experiment0" / "tokenizers" / "nemotron3_super_120b_bf16"
)

_tokenizer_lock = threading.Lock()
_tokenizer_cache: dict[str, Any] = {}


class LocalTokenizerError(RuntimeError):
    """Tokenizer load / template / artifact failure — fail closed."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_pinned_tokenizer(
    tokenizer_dir: Path,
    *,
    pinning: Optional[dict[str, Any]] = None,
):
    """Load AutoTokenizer offline after verifying pinned hashes. Cached per path."""
    key = str(tokenizer_dir.resolve())
    with _tokenizer_lock:
        if key in _tokenizer_cache:
            return _tokenizer_cache[key]

        pinning = pinning or load_pinning_manifest(
            tokenizer_dir / "PINNING_MANIFEST.json"
            if (tokenizer_dir / "PINNING_MANIFEST.json").exists()
            else DEFAULT_PINNING_MANIFEST
        )
        verify_artifact_hashes(tokenizer_dir, pinning)

        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise LocalTokenizerError(
                "transformers is required for LocalNemotronChatTokenCounter"
            ) from exc

        try:
            tok = AutoTokenizer.from_pretrained(
                str(tokenizer_dir),
                local_files_only=True,
                trust_remote_code=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise LocalTokenizerError(
                f"Failed to load pinned tokenizer from {tokenizer_dir}: {exc}"
            ) from exc

        template = tok.chat_template or ""
        expected_tmpl = pinning.get("chat_template_sha256")
        actual_tmpl = _sha256_text(template)
        if expected_tmpl and actual_tmpl != expected_tmpl:
            raise LocalTokenizerError(
                f"Chat template hash mismatch: loaded={actual_tmpl} "
                f"pinned={expected_tmpl}"
            )

        _tokenizer_cache[key] = {
            "tokenizer": tok,
            "pinning": pinning,
            "chat_template_sha256": actual_tmpl,
        }
        return _tokenizer_cache[key]


def clear_tokenizer_cache() -> None:
    with _tokenizer_lock:
        _tokenizer_cache.clear()


class LocalNemotronChatTokenCounter:
    """Count chat-templated input tokens for Nemotron-3-Super without inference.

    Always returns UNVERIFIED unless Stage-B `TokenizerQualificationEvidence`
    explicitly authorizes the bound provider profile (evidence_validated +
    hosted_qualification_status=PASSED + probe deltas all 0 + hash match).
    """

    def __init__(
        self,
        *,
        provider_profile: str = "nvidia-nim",
        model_id: str = "nvidia/nemotron-3-super-120b-a12b",
        tokenizer_dir: Optional[Path] = None,
        enable_thinking: bool = False,
        add_generation_prompt: bool = True,
        evidence: Optional[TokenizerQualificationEvidence] = None,
        evidence_path: Optional[Path] = None,
        load_evidence: bool = True,
    ):
        self.provider_profile = provider_profile
        self.model_id = model_id
        self.tokenizer_dir = Path(tokenizer_dir) if tokenizer_dir else DEFAULT_TOKENIZER_DIR
        self.enable_thinking = bool(enable_thinking)
        self.add_generation_prompt = bool(add_generation_prompt)
        self._bundle = load_pinned_tokenizer(self.tokenizer_dir)
        self._tokenizer = self._bundle["tokenizer"]
        self._pinning = self._bundle["pinning"]
        self._chat_template_sha256 = self._bundle["chat_template_sha256"]

        if evidence is not None:
            self._evidence = evidence
        elif load_evidence:
            try:
                self._evidence = load_qualification_evidence(evidence_path)
            except QualificationError:
                # Corrupt/incomplete evidence must not silently authorize;
                # treat as absent (UNVERIFIED). Surface via last_error.
                self._evidence = None
                self._evidence_load_error = "qualification evidence invalid"
            else:
                self._evidence_load_error = None
        else:
            self._evidence = None
            self._evidence_load_error = None

        self.last_count_meta: dict[str, Any] = {}

    @property
    def chat_template_sha256(self) -> str:
        return self._chat_template_sha256

    @property
    def is_provider_verified(self) -> bool:
        if self._evidence is None:
            return False
        return self._evidence.authorizes(
            provider_profile=self.provider_profile,
            model_id=self.model_id,
            pinning=self._pinning,
        )

    def assemble_messages(
        self, system: str, messages: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        return assemble_openai_chat_messages(system, messages)

    def render_templated_text(
        self, system: str, messages: list[dict[str, str]]
    ) -> str:
        openai_messages = self.assemble_messages(system, messages)
        return self._tokenizer.apply_chat_template(
            openai_messages,
            tokenize=False,
            add_generation_prompt=self.add_generation_prompt,
            enable_thinking=self.enable_thinking,
        )

    def count_ids(self, system: str, messages: list[dict[str, str]]) -> list[int]:
        openai_messages = self.assemble_messages(system, messages)
        ids = self._tokenizer.apply_chat_template(
            openai_messages,
            tokenize=True,
            add_generation_prompt=self.add_generation_prompt,
            enable_thinking=self.enable_thinking,
        )
        if hasattr(ids, "tolist"):
            ids = ids.tolist()
        if isinstance(ids, dict) and "input_ids" in ids:
            ids = ids["input_ids"]
            if hasattr(ids, "tolist"):
                ids = ids.tolist()
            if ids and isinstance(ids[0], list):
                ids = ids[0]
        return list(ids)

    def count_prompt_tokens(
        self, system: str, messages: list[dict[str, str]]
    ) -> tuple[Optional[int], TokenCountTrust]:
        # Never mutate caller inputs
        system_s = system
        messages_copy = [dict(m) for m in messages]

        if self.provider_profile == "unknown":
            self.last_count_meta = {
                "error": "unknown provider profile",
                "provider_profile": self.provider_profile,
            }
            return None, TokenCountTrust.UNAVAILABLE

        try:
            ids = self.count_ids(system_s, messages_copy)
            n = len(ids)
        except Exception as exc:  # noqa: BLE001
            self.last_count_meta = {"error": str(exc)}
            raise LocalTokenizerError(str(exc)) from exc

        trust = (
            TokenCountTrust.VERIFIED
            if self.is_provider_verified
            else TokenCountTrust.UNVERIFIED
        )
        # Operational metadata only — do not store message contents
        self.last_count_meta = {
            "prompt_tokens": n,
            "trust": trust.value,
            "provider_profile": self.provider_profile,
            "model_id": self.model_id,
            "tokenizer_revision": self._pinning.get("huggingface_revision"),
            "chat_template_sha256": self._chat_template_sha256,
            "enable_thinking": self.enable_thinking,
            "add_generation_prompt": self.add_generation_prompt,
            "n_messages": len(messages_copy) + (1 if system_s else 0),
            "qualification_authorized": self.is_provider_verified,
        }
        return n, trust
