"""Retry amendment v1 — infrastructure helpers (disabled until launch approval).

When RETRY_AMENDMENT_V1_ENABLED is False, scientific nested retries remain frozen.
When True (future activation), NVIDIA HTTP failure classes use physical-attempt
budgets and TerminalOperationalError so Actor/Witness cannot re-issue calls.

See EXPERIMENT0_NVIDIA_RETRY_AMENDMENT_PROPOSAL.md and
EXPERIMENT0_RETRY_AMENDMENT_V1_VALIDATION_REPORT.md.
"""

from __future__ import annotations

from typing import Any, Optional

from experiment0 import engineering_config as eng


class TerminalOperationalError(BaseException):
    """Terminal operational stop that bypasses Actor/Witness Exception retries.

    Intentionally **not** a subclass of Exception. Experiment 1 Actor._call_api and
    Witness.evaluate catch ``Exception`` and would otherwise re-issue HTTP calls
    after HTTP 429 / ambiguous transport failures. Malformed Witness JSON remains
    ``WitnessParseError`` (an Exception) and keeps frozen scientific retry rules.
    """

    def __init__(
        self,
        message: str,
        *,
        failure_class: str,
        status_code: Optional[int] = None,
        stop_reason: str = "STOPPED_FOR_REVIEW",
        amendment_id: str = "retry_amendment_v1",
        raw: Any = None,
    ):
        super().__init__(message)
        self.failure_class = failure_class
        self.status_code = status_code
        self.stop_reason = stop_reason
        self.amendment_id = amendment_id
        self.raw = raw


def amendment_enabled() -> bool:
    return bool(eng.RETRY_AMENDMENT_V1_ENABLED)


def amendment_provenance() -> dict[str, Any]:
    """Recordable ops block for a future clean N=60 run manifest (no secrets)."""
    return {
        "amendment_id": getattr(eng, "RETRY_AMENDMENT_V1_ID", "retry_amendment_v1"),
        "amendment_version": getattr(eng, "RETRY_AMENDMENT_V1_VERSION", "1"),
        "enabled": bool(eng.RETRY_AMENDMENT_V1_ENABLED),
        "physical_attempt_budgets": {
            "http_429": int(
                getattr(eng, "RETRY_AMENDMENT_V1_HTTP_429_MAX_PHYSICAL_ATTEMPTS", 1)
            ),
            "http_5xx": int(
                getattr(eng, "RETRY_AMENDMENT_V1_HTTP_5XX_MAX_PHYSICAL_ATTEMPTS", 2)
            ),
            "ambiguous_timeout": int(
                getattr(
                    eng,
                    "RETRY_AMENDMENT_V1_AMBIGUOUS_TIMEOUT_MAX_PHYSICAL_ATTEMPTS",
                    1,
                )
            ),
        },
        "global_pacing": {
            "enabled": bool(eng.NIM_HTTP_PACING_ENABLED),
            "min_start_to_start_sec": float(eng.NIM_HTTP_MIN_START_TO_START_SEC),
        },
        "witness_json_policy": "frozen_scientific_unchanged",
        "note": (
            "A clean N=60 must not mix amended and non-amended execution policies."
        ),
    }


def classify_http_for_amendment(status_code: Optional[int]) -> str:
    if status_code == 429:
        return "http_429"
    if status_code is not None and status_code >= 500:
        return "http_5xx"
    return "other"


def is_ambiguous_timeout(exc: BaseException) -> bool:
    """Heuristic for transport timeouts without a clear HTTP status."""
    if isinstance(exc, TimeoutError):
        return True
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timed out" in msg or "timeout" in msg:
        return True
    # urllib.error.URLError wrapping a socket timeout
    reason = getattr(exc, "reason", None)
    if reason is not None and is_ambiguous_timeout(reason):  # type: ignore[arg-type]
        return True
    return False


def raise_terminal(
    message: str,
    *,
    failure_class: str,
    status_code: Optional[int] = None,
    raw: Any = None,
) -> None:
    raise TerminalOperationalError(
        message,
        failure_class=failure_class,
        status_code=status_code,
        stop_reason="STOPPED_FOR_REVIEW",
        amendment_id=getattr(eng, "RETRY_AMENDMENT_V1_ID", "retry_amendment_v1"),
        raw=raw,
    )


def maybe_stop_on_429(status_code: Optional[int], raw: str = "") -> None:
    """If amendment enabled, raise TerminalOperationalError on HTTP 429."""
    if not amendment_enabled():
        return
    if not eng.RETRY_AMENDMENT_V1_STOP_ON_HTTP_429:
        return
    if status_code != 429:
        return
    raise_terminal(
        f"HTTP 429 rate limited — retry amendment v1 terminal stop "
        f"(no automatic retry): {raw[:300]}",
        failure_class="http_429",
        status_code=429,
        raw=raw[:1000],
    )


def http_429_budget() -> int:
    return int(getattr(eng, "RETRY_AMENDMENT_V1_HTTP_429_MAX_PHYSICAL_ATTEMPTS", 1))


def http_5xx_budget() -> int:
    return int(getattr(eng, "RETRY_AMENDMENT_V1_HTTP_5XX_MAX_PHYSICAL_ATTEMPTS", 2))


def ambiguous_timeout_budget() -> int:
    return int(
        getattr(eng, "RETRY_AMENDMENT_V1_AMBIGUOUS_TIMEOUT_MAX_PHYSICAL_ATTEMPTS", 1)
    )


def transient_5xx_retry_budget() -> int:
    """Compatibility alias: max physical attempts for 5xx under amendment."""
    if not amendment_enabled():
        return 0
    return http_5xx_budget()
