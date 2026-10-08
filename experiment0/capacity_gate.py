"""Provider-context-aware capacity hard gate (Experiment 0 engineering).

Rules:
- Enforce frozen 85% capacity fraction.
- Require a configured, verified provider context limit (no universal 1M assumption).
- Fail closed if context capacity or trustworthy token counts are unavailable.
- Do not silently truncate, summarize, or modify prompts.
- Do not authorize scientific requests with approximate / unverified token estimates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol


class TokenCountTrust(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"


class CapacityConfigurationError(RuntimeError):
    """Provider context not configured/verified — fail closed before any request."""


class CapacityGateError(RuntimeError):
    """Per-request capacity or trust failure — fail closed; do not truncate."""


class TokenCounter(Protocol):
    """Exact token counter for a serialized chat request.

    Implementations that cannot produce provider-qualified exact counts must
    return trust=UNVERIFIED or UNAVAILABLE (never invent a verified estimate).
    """

    def count_prompt_tokens(
        self, system: str, messages: list[dict[str, str]]
    ) -> tuple[Optional[int], TokenCountTrust]:
        ...


@dataclass(frozen=True)
class CapacityGate:
    verified_context_limit: Optional[int]
    fraction: float = 0.85
    context_limit_verified: bool = False
    provider_profile: str = "unknown"

    def budget_tokens(self) -> int:
        if not self.context_limit_verified:
            raise CapacityConfigurationError(
                f"Provider context capacity not verified for profile "
                f"{self.provider_profile!r} — fail closed"
            )
        if self.verified_context_limit is None or int(self.verified_context_limit) <= 0:
            raise CapacityConfigurationError(
                f"Provider context capacity unavailable for profile "
                f"{self.provider_profile!r} — fail closed"
            )
        return int(int(self.verified_context_limit) * float(self.fraction))

    def evaluate(
        self,
        *,
        prompt_tokens: Optional[int],
        reserved_output_tokens: int,
        token_count_trust: TokenCountTrust,
    ) -> dict[str, Any]:
        """Return capacity arithmetic; does not raise on over-budget (caller may)."""
        # Configuration / trust failures are hard errors even for evaluate().
        budget = self.budget_tokens()
        if token_count_trust != TokenCountTrust.VERIFIED:
            raise CapacityGateError(
                f"Trustworthy token count unavailable "
                f"(trust={token_count_trust.value}) — fail closed"
            )
        if prompt_tokens is None:
            raise CapacityGateError(
                "Prompt token count unavailable — fail closed"
            )
        lhs = int(prompt_tokens) + int(reserved_output_tokens)
        return {
            "prompt_tokens": int(prompt_tokens),
            "reserved_output": int(reserved_output_tokens),
            "lhs": lhs,
            "rhs": budget,
            "pass": lhs <= budget,
            "context_limit": int(self.verified_context_limit or 0),
            "fraction": float(self.fraction),
            "token_count_trust": token_count_trust.value,
            "provider_profile": self.provider_profile,
        }

    def assert_request_allowed(
        self,
        *,
        prompt_tokens: Optional[int],
        reserved_output_tokens: int,
        token_count_trust: TokenCountTrust,
        role: str = "request",
    ) -> dict[str, Any]:
        result = self.evaluate(
            prompt_tokens=prompt_tokens,
            reserved_output_tokens=reserved_output_tokens,
            token_count_trust=token_count_trust,
        )
        if not result["pass"]:
            raise CapacityGateError(
                f"Capacity gate failed for {role}: "
                f"prompt_tokens+reserved_output={result['lhs']} > "
                f"0.85*context={result['rhs']} "
                f"(limit={result['context_limit']}, profile={self.provider_profile})"
            )
        return result


class UnavailableTokenCounter:
    """Default scientific-path counter: no approximate authorization."""

    def count_prompt_tokens(
        self, system: str, messages: list[dict[str, str]]
    ) -> tuple[Optional[int], TokenCountTrust]:
        return None, TokenCountTrust.UNAVAILABLE


class UnverifiedEstimateCounter:
    """Explicitly unverified estimates — must never authorize a scientific request."""

    def __init__(self, estimate: int):
        self.estimate = estimate

    def count_prompt_tokens(
        self, system: str, messages: list[dict[str, str]]
    ) -> tuple[Optional[int], TokenCountTrust]:
        return int(self.estimate), TokenCountTrust.UNVERIFIED


class VerifiedFixedTokenCounter:
    """Test / injected adapter: returns a fixed verified count for the request."""

    def __init__(self, prompt_tokens: int):
        self.prompt_tokens = int(prompt_tokens)

    def count_prompt_tokens(
        self, system: str, messages: list[dict[str, str]]
    ) -> tuple[Optional[int], TokenCountTrust]:
        return self.prompt_tokens, TokenCountTrust.VERIFIED


class VerifiedCallableTokenCounter:
    """Test adapter: compute verified tokens from the exact serialized request."""

    def __init__(self, fn):
        self._fn = fn

    def count_prompt_tokens(
        self, system: str, messages: list[dict[str, str]]
    ) -> tuple[Optional[int], TokenCountTrust]:
        return int(self._fn(system, messages)), TokenCountTrust.VERIFIED


class LiveProviderTokenCounter:
    """Exact provider count via count_prompt_tokens (extra API call per request).

    Not enabled by default on the scientific path — rate-limit and cost
    consequences must be assessed before use (see P0 implementation report).
    """

    def __init__(self, provider: Any, *, model: str, enable_thinking: bool = False):
        self._provider = provider
        self._model = model
        self._enable_thinking = enable_thinking

    def count_prompt_tokens(
        self, system: str, messages: list[dict[str, str]]
    ) -> tuple[Optional[int], TokenCountTrust]:
        from experiment0.providers.base import ProviderRequest

        req = ProviderRequest(
            model=self._model,
            system=system,
            messages=list(messages),
            max_tokens=1,
            temperature=0.0,
            enable_thinking=self._enable_thinking,
            purpose="capacity_gate_per_request",
        )
        n = int(self._provider.count_prompt_tokens(req))
        return n, TokenCountTrust.VERIFIED


def gate_from_provider_profile(
    profile_name: str,
    *,
    profiles: Optional[dict[str, dict]] = None,
    fraction: float = 0.85,
) -> CapacityGate:
    from experiment0 import engineering_config as eng

    table = profiles if profiles is not None else eng.PROVIDER_CONTEXT_PROFILES
    if profile_name not in table:
        return CapacityGate(
            verified_context_limit=None,
            fraction=fraction,
            context_limit_verified=False,
            provider_profile=profile_name,
        )
    row = table[profile_name]
    return CapacityGate(
        verified_context_limit=row.get("verified_context_limit"),
        fraction=fraction,
        context_limit_verified=bool(row.get("context_limit_verified")),
        provider_profile=profile_name,
    )


class CapacityGatingAnthropicClient:
    """Wrap an Anthropic-shaped client; assert capacity on the exact create() payload.

    Uses the caller's max_tokens as the role-specific output budget (Actor 800 /
    Witness 1600). Does not modify prompts.
    """

    def __init__(
        self,
        inner: Any,
        *,
        gate: CapacityGate,
        token_counter: TokenCounter,
        role: str = "request",
    ):
        self._inner = inner
        self._gate = gate
        self._token_counter = token_counter
        self._role = role
        self.messages = self
        self.last_capacity_check: Optional[dict[str, Any]] = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def last_normalized(self) -> Any:
        return getattr(self._inner, "last_normalized", None)

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        system: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Any:
        prompt_tokens, trust = self._token_counter.count_prompt_tokens(
            system, list(messages)
        )
        self.last_capacity_check = self._gate.assert_request_allowed(
            prompt_tokens=prompt_tokens,
            reserved_output_tokens=int(max_tokens),
            token_count_trust=trust,
            role=self._role,
        )
        return self._inner.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
            **kwargs,
        )
