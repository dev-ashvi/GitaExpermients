"""NVIDIA NIM OpenAI-compatible Chat Completions provider (Experiment 0 only)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, Optional

from experiment0.http_pacing import GlobalHttpPacer
from experiment0.providers.base import (
    NormalizedLLMResponse,
    ProviderError,
    ProviderRequest,
)
from experiment0.providers.message_assembly import assemble_openai_chat_messages
from experiment0.retry_amendment import (
    TerminalOperationalError,
    amendment_enabled,
    http_5xx_budget,
    is_ambiguous_timeout,
    maybe_stop_on_429,
    raise_terminal,
)


class NimChatProvider:
    """OpenAI-compatible chat completions against integrate.api.nvidia.com."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_key_env: str = "NIM_API_KEY",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        max_retries: int = 3,
        retry_base_delay_sec: float = 1.0,
        timeout_sec: float = 600.0,
        send_top_p: bool = False,
        send_sampling_seed: bool = False,
        http_pacer: Optional[GlobalHttpPacer] = None,
    ):
        key = api_key if api_key is not None else os.environ.get(api_key_env, "").strip()
        if not key:
            raise ProviderError(
                f"{api_key_env} is not set. Export the key in the environment; "
                "it must never be hardcoded.",
                retriable=False,
            )
        self._api_key = key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.retry_base_delay_sec = retry_base_delay_sec
        self.timeout_sec = timeout_sec
        self.send_top_p = send_top_p
        self.send_sampling_seed = send_sampling_seed
        # never expose key via repr
        self._api_key_env = api_key_env
        self.http_pacer = http_pacer

    def __repr__(self) -> str:
        return f"NimChatProvider(base_url={self.base_url!r}, key_env={self._api_key_env!r})"

    def complete(self, request: ProviderRequest) -> NormalizedLLMResponse:
        if amendment_enabled():
            return self._complete_amendment_v1(request)
        return self._complete_frozen(request)

    def _complete_frozen(self, request: ProviderRequest) -> NormalizedLLMResponse:
        last_err: Optional[Exception] = None
        retries_used = 0
        budget = int(self.max_retries)
        for attempt in range(budget):
            t0 = time.time()
            try:
                payload = self._build_payload(request)
                status, parsed, raw = self._post_json(
                    f"{self.base_url}/chat/completions",
                    payload,
                    role=_role_from_purpose(request.purpose),
                    purpose=request.purpose or "complete",
                )
                latency_ms = int((time.time() - t0) * 1000)
                if status == 429 or status >= 500:
                    raise ProviderError(
                        f"Transient NIM HTTP {status}: {raw[:300]}",
                        status_code=status,
                        retriable=True,
                        raw=raw[:1000],
                    )
                if status != 200:
                    raise ProviderError(
                        f"NIM HTTP {status}: {raw[:500]}",
                        status_code=status,
                        retriable=False,
                        raw=raw[:2000],
                    )
                return self._normalize(parsed, latency_ms=latency_ms, retries=retries_used)
            except ProviderError as e:
                last_err = e
                if e.retriable and attempt + 1 < budget:
                    retries_used += 1
                    time.sleep(self.retry_base_delay_sec * (2**attempt))
                    continue
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt + 1 < budget:
                    retries_used += 1
                    time.sleep(self.retry_base_delay_sec * (2**attempt))
                    continue
                raise ProviderError(
                    f"NIM request failed after retries: {e}",
                    retriable=False,
                    raw=str(e),
                ) from e
        raise ProviderError(f"NIM request failed: {last_err}", retriable=False)

    def _complete_amendment_v1(self, request: ProviderRequest) -> NormalizedLLMResponse:
        """Physical-attempt budgets across the logical call (no outer-layer reissue).

        - HTTP 429: exactly 1 physical attempt → TerminalOperationalError
        - HTTP 5xx: at most 2 physical attempts → then TerminalOperationalError
        - Ambiguous timeout / transport: 1 physical attempt → TerminalOperationalError
        """
        physical = 0
        retries_used = 0
        budget_5xx = http_5xx_budget()
        while True:
            t0 = time.time()
            try:
                payload = self._build_payload(request)
                status, parsed, raw = self._post_json(
                    f"{self.base_url}/chat/completions",
                    payload,
                    role=_role_from_purpose(request.purpose),
                    purpose=request.purpose or "complete",
                )
                physical += 1
                latency_ms = int((time.time() - t0) * 1000)
                maybe_stop_on_429(status, raw)
                if status >= 500:
                    if physical >= budget_5xx:
                        raise_terminal(
                            f"HTTP {status} exhausted amendment v1 5xx budget "
                            f"({budget_5xx} physical attempts): {raw[:300]}",
                            failure_class="http_5xx_exhausted",
                            status_code=status,
                            raw=raw[:1000],
                        )
                    retries_used += 1
                    time.sleep(self.retry_base_delay_sec * (2 ** (physical - 1)))
                    continue
                if status != 200:
                    raise_terminal(
                        f"NIM HTTP {status}: {raw[:500]}",
                        failure_class=f"http_{status}",
                        status_code=status,
                        raw=raw[:2000],
                    )
                return self._normalize(
                    parsed, latency_ms=latency_ms, retries=retries_used
                )
            except TerminalOperationalError:
                raise
            except ProviderError:
                raise
            except Exception as e:  # noqa: BLE001
                # Count the failed physical attempt; never blind-reissue under v1.
                physical += 1
                if is_ambiguous_timeout(e):
                    raise_terminal(
                        f"Ambiguous transport timeout — amendment v1 terminal "
                        f"stop (no blind re-issuance): {e}",
                        failure_class="ambiguous_timeout",
                        status_code=None,
                        raw=str(e),
                    )
                raise_terminal(
                    f"Transport failure — amendment v1 terminal stop: {e}",
                    failure_class="transport_failure",
                    status_code=None,
                    raw=str(e),
                )

    def count_prompt_tokens(self, request: ProviderRequest) -> int:
        """Exact provider-side input token count via usage.prompt_tokens (max_tokens=1)."""
        count_req = ProviderRequest(
            model=request.model,
            system=request.system,
            messages=list(request.messages),
            max_tokens=1,
            temperature=0.0,
            enable_thinking=request.enable_thinking,
            purpose=request.purpose or "token_count",
        )
        if amendment_enabled():
            # Reuse amendment complete path with max_tokens=1 payload via dedicated loop
            return self._count_amendment_v1(count_req)
        return self._count_frozen(count_req)

    def _count_frozen(self, count_req: ProviderRequest) -> int:
        last_err: Optional[Exception] = None
        budget = int(self.max_retries)
        for attempt in range(budget):
            try:
                payload = self._build_payload(count_req)
                status, parsed, raw = self._post_json(
                    f"{self.base_url}/chat/completions",
                    payload,
                    role=_role_from_purpose(count_req.purpose),
                    purpose=count_req.purpose or "token_count",
                )
                if status == 429 or status >= 500:
                    raise ProviderError(
                        f"Transient NIM HTTP {status}",
                        status_code=status,
                        retriable=True,
                        raw=raw[:500],
                    )
                if status != 200:
                    raise ProviderError(
                        f"Token count HTTP {status}: {raw[:400]}",
                        status_code=status,
                        retriable=False,
                    )
                usage = (parsed or {}).get("usage") or {}
                pt = usage.get("prompt_tokens")
                if pt is None:
                    raise ProviderError(
                        "NIM response missing usage.prompt_tokens",
                        retriable=False,
                        raw=parsed,
                    )
                return int(pt)
            except ProviderError as e:
                last_err = e
                if e.retriable and attempt + 1 < budget:
                    time.sleep(self.retry_base_delay_sec * (2**attempt))
                    continue
                raise
        raise ProviderError(f"Token count failed: {last_err}")

    def _count_amendment_v1(self, count_req: ProviderRequest) -> int:
        physical = 0
        budget_5xx = http_5xx_budget()
        while True:
            try:
                payload = self._build_payload(count_req)
                status, parsed, raw = self._post_json(
                    f"{self.base_url}/chat/completions",
                    payload,
                    role=_role_from_purpose(count_req.purpose),
                    purpose=count_req.purpose or "token_count",
                )
                physical += 1
                maybe_stop_on_429(status, raw)
                if status >= 500:
                    if physical >= budget_5xx:
                        raise_terminal(
                            f"Token-count HTTP {status} exhausted 5xx budget",
                            failure_class="http_5xx_exhausted",
                            status_code=status,
                            raw=raw[:500],
                        )
                    time.sleep(self.retry_base_delay_sec * (2 ** (physical - 1)))
                    continue
                if status != 200:
                    raise_terminal(
                        f"Token count HTTP {status}: {raw[:400]}",
                        failure_class=f"http_{status}",
                        status_code=status,
                        raw=raw[:500],
                    )
                usage = (parsed or {}).get("usage") or {}
                pt = usage.get("prompt_tokens")
                if pt is None:
                    raise_terminal(
                        "NIM response missing usage.prompt_tokens",
                        failure_class="missing_usage",
                        status_code=status,
                        raw=parsed,
                    )
                return int(pt)
            except TerminalOperationalError:
                raise
            except Exception as e:  # noqa: BLE001
                physical += 1
                if is_ambiguous_timeout(e):
                    raise_terminal(
                        f"Ambiguous timeout during token count: {e}",
                        failure_class="ambiguous_timeout",
                        raw=str(e),
                    )
                raise_terminal(
                    f"Transport failure during token count: {e}",
                    failure_class="transport_failure",
                    raw=str(e),
                )

    def _build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        messages = assemble_openai_chat_messages(request.system, request.messages)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "chat_template_kwargs": {"enable_thinking": bool(request.enable_thinking)},
        }
        # Explicitly do not inject top_p / seed unless configured (Exp1 mapping)
        if self.send_top_p:
            raise ProviderError(
                "SEND_TOP_P is True but Experiment 0 mapping forbids silent top_p; "
                "set an explicit scientific value in config before enabling.",
                retriable=False,
            )
        if self.send_sampling_seed:
            raise ProviderError(
                "SEND_SAMPLING_SEED is True but Experiment 1 does not control "
                "sampling via API seed; refuse to invent a mapping.",
                retriable=False,
            )
        return payload

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        role: str = "unknown",
        purpose: str = "",
    ) -> tuple[int, Any, str]:
        """Sole HTTP egress. Global pacing (if configured) applies here."""

        def _do_post() -> tuple[int, Any, str]:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    status = int(getattr(resp, "status", 200) or 200)
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
                status = int(e.code)
                try:
                    parsed = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    parsed = None
                return status, parsed, raw
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError as e:
                raise ProviderError(
                    f"NIM returned non-JSON body: {e}",
                    status_code=status,
                    retriable=False,
                    raw=raw[:1000],
                ) from e
            return status, parsed, raw

        if self.http_pacer is None:
            return _do_post()

        with self.http_pacer.gated_attempt(role=role, purpose=purpose) as attempt:
            try:
                status, parsed, raw = _do_post()
                attempt["http_status"] = status
                attempt["ok"] = status == 200
                if status != 200:
                    attempt["error_class"] = f"http_{status}"
                return status, parsed, raw
            except Exception as exc:  # noqa: BLE001
                attempt["ok"] = False
                attempt["error_class"] = type(exc).__name__
                raise

    def attach_http_pacer(self, pacer: Optional[GlobalHttpPacer]) -> None:
        self.http_pacer = pacer

    def _normalize(
        self, parsed: Any, *, latency_ms: int, retries: int
    ) -> NormalizedLLMResponse:
        if not isinstance(parsed, dict):
            raise ProviderError("NIM JSON root must be an object", retriable=False)
        text = _extract_assistant_text(parsed)
        usage = parsed.get("usage") or {}
        choices = parsed.get("choices") or []
        finish = None
        if choices and isinstance(choices[0], dict):
            finish = choices[0].get("finish_reason")
        if not text:
            raise ProviderError(
                "NIM response contained empty assistant text",
                retriable=False,
                raw=parsed,
            )
        return NormalizedLLMResponse(
            text=text,
            model_id_returned=parsed.get("model"),
            prompt_tokens=_opt_int(usage.get("prompt_tokens")),
            completion_tokens=_opt_int(usage.get("completion_tokens")),
            total_tokens=_opt_int(usage.get("total_tokens")),
            finish_reason=finish if isinstance(finish, str) else None,
            latency_ms=latency_ms,
            retries=retries,
            raw_provider_metadata={
                "id": parsed.get("id"),
                "usage": usage,
                "finish_reason": finish,
                "system_fingerprint": parsed.get("system_fingerprint"),
            },
        )


def _opt_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    return int(v)


def _extract_assistant_text(parsed: dict[str, Any]) -> str:
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice0 = choices[0]
    if not isinstance(choice0, dict):
        return ""
    message = choice0.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    # Some reasoning models may put visible answer only after thinking;
    # with enable_thinking=False content should be the answer.
    return ""


def _role_from_purpose(purpose: str) -> str:
    p = (purpose or "").lower()
    if "witness" in p:
        return "witness"
    if "actor" in p:
        return "actor"
    if "token" in p:
        return "token_count"
    return "unknown"


class NimAnthropicCompatClient:
    """Duck-types Anthropic `client.messages.create` for reuse of Exp1 Actor/Witness.

    Experiment 1 continues to use `anthropic.Anthropic` unchanged.
    Experiment 0 may pass this compatibility client into the same classes
    without modifying Actor/Witness source.
    """

    def __init__(
        self,
        provider: NimChatProvider,
        *,
        enable_thinking: bool = False,
        purpose: str = "",
    ):
        self._provider = provider
        self._enable_thinking = enable_thinking
        self._purpose = purpose
        self.messages = self
        self.last_normalized: Optional[NormalizedLLMResponse] = None

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        system: str,
        messages: list[dict[str, str]],
        **_kwargs: Any,
    ) -> Any:
        req = ProviderRequest(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            enable_thinking=self._enable_thinking,
            purpose=self._purpose or "complete",
        )
        norm = self._provider.complete(req)
        self.last_normalized = norm
        # Anthropic-shaped response object
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=norm.text)],
            usage=SimpleNamespace(
                input_tokens=norm.prompt_tokens or 0,
                output_tokens=norm.completion_tokens or 0,
            ),
            model=norm.model_id_returned or model,
            stop_reason=norm.finish_reason,
            _normalized=norm,
        )
