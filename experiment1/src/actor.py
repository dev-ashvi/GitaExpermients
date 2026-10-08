"""Actor LLM — research synthesis agent.

Isolation invariant: Actor must never see Witness existence, scores, verdict,
evaluation language, condition, phase, OSM state, or experiment hypothesis.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

from config.experiment_config import (
    ACTOR_MODEL,
    ACTOR_TASK_FRAMING,
    ACTOR_TEMPERATURE,
    API_MAX_RETRIES,
    API_RETRY_BASE_DELAY_SEC,
    DOCUMENTS_DIR,
    MAX_TOKENS_ACTOR,
)
from src.types_util import build_source_packet, load_text


# Experiment / evaluator metadata patterns — NOT generic constitutional English.
# See PATCH isolation-validator correction: "Constitutive condition" and
# "Evaluation Principle" must NOT be treated as leakage.
# Current frozen constitution still fails on Witness footer — OPEN_ISSUES ISSUE-004.
_ACTOR_LEAKAGE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("witness_protocol", r"witness[_\s-]*protocol"),
    ("witness protocol", r"witness\s+protocol"),
    ("companion document: witness", r"companion\s+document\s*:\s*[^\n]*witness"),
    ("you are being evaluated", r"you\s+are\s+being\s+evaluated"),
    ("you are being scored", r"you\s+are\s+being\s+scored"),
    ("experimental condition", r"experimental\s+condition"),
    ("condition 1", r"\bcondition\s*1\b"),
    ("condition 2", r"\bcondition\s*2\b"),
    ("condition 3", r"\bcondition\s*3\b"),
    ("salience phase", r"salience\s+phase"),
    ("obstruction phase", r"obstruction\s+phase"),
    ("experiment hypothesis", r"experiment(?:al)?\s+hypothesis"),
    ("osm state", r"\bosm\s+state\b"),
    ("witness score", r"witness\s+score"),
    ("witness verdict", r"witness\s+verdict"),
    # Standalone evaluator noun (not part of ordinary prose like "eye-witness"
    # scientific claims — require clear Witness-system capitalization or label)
    ("Witness (evaluator)", r"(?<![A-Za-z])Witness(?![A-Za-z_])"),
)


class ActorIsolationError(RuntimeError):
    pass


def find_actor_system_prompt_violations(prompt: str) -> list[str]:
    """Return experiment/evaluator metadata leaks in the Actor system prompt.

    Detects Witness/experiment infrastructure references.
    Does NOT flag generic constitutional phrases such as
    "Constitutive condition", "Evaluation Principle", or "evaluate the evidence".
    """
    found: list[str] = []
    for label, pattern in _ACTOR_LEAKAGE_PATTERNS:
        if re.search(pattern, prompt, flags=re.IGNORECASE):
            # Avoid double-counting Witness capital-W when witness_protocol already hit
            if label == "Witness (evaluator)" and any(
                x.startswith("witness") for x in found
            ):
                continue
            found.append(label)
    return found


def validate_actor_system_prompt(prompt: str) -> None:
    """Fail if the final Actor system prompt contains experiment/evaluator metadata.

    Scans the ENTIRE prompt (constitution + sources + framing), not only
    dynamically appended messages.
    """
    found = find_actor_system_prompt_violations(prompt)
    if found:
        raise ActorIsolationError(
            "Actor system prompt contains prohibited Witness/experiment metadata: "
            + ", ".join(found)
            + ". Replace actor_constitution_v1.md with a cleaned version "
            "(see OPEN_ISSUES.md ISSUE-004). Validation is not bypassed."
        )


def build_actor_system_prompt(
    constitution_text: str,
    source_packet_text: str,
    task_framing: str = ACTOR_TASK_FRAMING,
    *,
    skip_isolation_validation: bool = False,
) -> str:
    """Build Actor system prompt: constitution + sources + task framing only.

    By default validates the full prompt against isolation rules.
    skip_isolation_validation is ONLY for tests that assert the failure mode
    of the current frozen constitution; production paths must not skip.
    """
    prompt = (
        f"{task_framing}\n\n"
        f"=== CONSTITUTION ===\n{constitution_text}\n\n"
        f"=== SOURCE PACKET ===\n{source_packet_text}\n"
    )
    if not skip_isolation_validation:
        validate_actor_system_prompt(prompt)
    return prompt


class Actor:
    """Multi-turn Actor with three-part history commit (prompt, output, user_response)."""

    def __init__(
        self,
        client: Any,
        system_prompt: str,
        *,
        model: str = ACTOR_MODEL,
        temperature: float = ACTOR_TEMPERATURE,
        max_tokens: int = MAX_TOKENS_ACTOR,
        api_call_hook: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.client = client
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.conversation_history: list[dict[str, str]] = []
        self.api_call_hook = api_call_hook  # for tests / inspection
        self.last_input_tokens: int = 0
        self.last_output_tokens: int = 0
        self.last_latency_ms: int = 0
        self.last_messages_sent: list[dict[str, str]] = []

    @classmethod
    def from_files(cls, client: Any, **kwargs: Any) -> "Actor":
        constitution = load_text(DOCUMENTS_DIR / "actor_constitution_v1.md")
        sources = build_source_packet()
        system_prompt = build_actor_system_prompt(constitution, sources)
        return cls(client, system_prompt, **kwargs)

    def generate(self, user_prompt: str) -> str:
        """Generate Actor output for the current turn (initial generation).

        Messages = committed history + current user prompt.
        Does not commit; caller must commit_turn after the turn completes.
        """
        messages = list(self.conversation_history)
        messages.append({"role": "user", "content": user_prompt})
        return self._send(messages)

    def generate_revision(
        self,
        user_prompt: str,
        candidate_output: str,
        buddhi_feedback: str,
    ) -> str:
        """Regenerate against a temporary context that includes the candidate.

        Temporary messages (NOT committed to long-term history):
          committed history
          [user] user_prompt
          [assistant] candidate_output   ← verbatim candidate being revised
          [user] buddhi_feedback

        Intermediate failed revisions must not be commit_turn'd.
        """
        if not buddhi_feedback:
            raise ValueError("buddhi_feedback required for generate_revision")
        fb_lower = buddhi_feedback.lower()
        for forbidden in (
            "overall_score",
            "verdict:",
            "witness score",
            "truth:",
            "uncertainty score",
        ):
            if forbidden in fb_lower:
                raise ActorIsolationError(
                    f"Buddhi feedback contains Witness leakage: {forbidden}"
                )

        messages = list(self.conversation_history)
        messages.append({"role": "user", "content": user_prompt})
        messages.append({"role": "assistant", "content": candidate_output})
        messages.append({"role": "user", "content": buddhi_feedback})
        return self._send(messages)

    def commit_turn(
        self,
        user_prompt: str,
        actor_output: str,
        user_response: str,
    ) -> None:
        """Commit three-part turn to history. user_response is REQUIRED (manipulation)."""
        if user_prompt is None or actor_output is None:
            raise ValueError("user_prompt and actor_output required")
        if user_response is None:
            raise ValueError(
                "user_response must be committed to Actor history "
                "(experimental manipulation)"
            )
        self.conversation_history.append({"role": "user", "content": user_prompt})
        self.conversation_history.append(
            {"role": "assistant", "content": actor_output}
        )
        self.conversation_history.append({"role": "user", "content": user_response})

    def history_contains(self, text: str) -> bool:
        return any(text in m.get("content", "") for m in self.conversation_history)

    def _send(self, messages: list[dict[str, str]]) -> str:
        self.last_messages_sent = [dict(m) for m in messages]
        if self.api_call_hook:
            self.api_call_hook(
                {
                    "system": self.system_prompt,
                    "messages": self.last_messages_sent,
                    "model": self.model,
                }
            )
        text, in_tok, out_tok, latency = self._call_api(messages)
        self.last_input_tokens = in_tok
        self.last_output_tokens = out_tok
        self.last_latency_ms = latency
        return text

    def _call_api(
        self, messages: list[dict[str, str]]
    ) -> tuple[str, int, int, int]:
        last_err: Optional[Exception] = None
        for attempt in range(API_MAX_RETRIES):
            t0 = time.time()
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=self.system_prompt,
                    messages=messages,
                )
                latency = int((time.time() - t0) * 1000)
                text = "".join(
                    block.text
                    for block in response.content
                    if getattr(block, "type", None) == "text"
                    or hasattr(block, "text")
                )
                usage = getattr(response, "usage", None)
                in_tok = int(getattr(usage, "input_tokens", 0) or 0)
                out_tok = int(getattr(usage, "output_tokens", 0) or 0)
                return text, in_tok, out_tok, latency
            except Exception as e:  # noqa: BLE001 — retry transient API errors
                last_err = e
                if attempt + 1 < API_MAX_RETRIES:
                    time.sleep(API_RETRY_BASE_DELAY_SEC * (2 ** attempt))
        raise RuntimeError(f"Actor API failed after retries: {last_err}") from last_err
