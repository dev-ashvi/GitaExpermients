"""Normalized LLM provider contract for Experiment 0."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


class ProviderError(RuntimeError):
    """Non-retriable or exhausted-retry provider failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retriable: bool = False,
        raw: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retriable = retriable
        self.raw = raw


@dataclass
class ProviderRequest:
    model: str
    system: str
    messages: list[dict[str, str]]
    max_tokens: int
    temperature: float
    enable_thinking: bool = False
    # Audit-only fields (never secrets)
    purpose: str = ""


@dataclass
class NormalizedLLMResponse:
    """Provider-agnostic completion surface consumed by experimental code."""

    text: str
    model_id_returned: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    finish_reason: Optional[str]
    latency_ms: int
    retries: int
    raw_provider_metadata: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text)


class LLMProvider(Protocol):
    def complete(self, request: ProviderRequest) -> NormalizedLLMResponse: ...
