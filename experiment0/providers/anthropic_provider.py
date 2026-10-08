"""Anthropic Messages adapter (Experiment 1 path documentation / optional use).

Experiment 1 continues to call `anthropic.Anthropic` directly and is unchanged.
This module exists so both providers share the same NormalizedLLMResponse contract
if future code wants a uniform interface without touching Exp1 episode logic.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from experiment0.providers.base import (
    NormalizedLLMResponse,
    ProviderError,
    ProviderRequest,
)


class AnthropicMessagesProvider:
    """Thin wrapper around an Anthropic SDK client."""

    def __init__(self, client: Any, *, max_retries: int = 3, retry_base_delay_sec: float = 1.0):
        self.client = client
        self.max_retries = max_retries
        self.retry_base_delay_sec = retry_base_delay_sec

    def complete(self, request: ProviderRequest) -> NormalizedLLMResponse:
        last_err: Optional[Exception] = None
        retries = 0
        for attempt in range(self.max_retries):
            t0 = time.time()
            try:
                response = self.client.messages.create(
                    model=request.model,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    system=request.system,
                    messages=request.messages,
                )
                latency_ms = int((time.time() - t0) * 1000)
                text = "".join(
                    block.text
                    for block in response.content
                    if getattr(block, "type", None) == "text" or hasattr(block, "text")
                )
                usage = getattr(response, "usage", None)
                return NormalizedLLMResponse(
                    text=text,
                    model_id_returned=getattr(response, "model", None) or request.model,
                    prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                    total_tokens=int(getattr(usage, "input_tokens", 0) or 0)
                    + int(getattr(usage, "output_tokens", 0) or 0),
                    finish_reason=getattr(response, "stop_reason", None),
                    latency_ms=latency_ms,
                    retries=retries,
                    raw_provider_metadata={"provider": "anthropic"},
                )
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt + 1 < self.max_retries:
                    retries += 1
                    time.sleep(self.retry_base_delay_sec * (2**attempt))
                    continue
                raise ProviderError(
                    f"Anthropic request failed: {e}", retriable=False
                ) from e
        raise ProviderError(f"Anthropic request failed: {last_err}")
