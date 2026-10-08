"""Episode runner — 25-turn experimental episode loop.

Critical order (frozen):
1. Actor generates
2. Witness evaluates raw output
3. Phase gate — Buddhi obstructs ONLY in turns 15-24
4. Revision loop only if obstruction decision is revise/reject
5. User response from witness_raw (initial output)
6. OSM classifies final output
7. Actor history updated with user_response verbatim
8. Ledger written (metrics null)

Resume policy: FAIL-AND-RESTART only. Never resume a partial episode with
empty/reconstructed Actor history (PATCH 2).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from config.experiment_config import (
    ACTOR_MODEL,
    ACTOR_TEMPERATURE,
    EXPERIMENT_ID,
    MAX_REGENERATIONS,
    OBSTRUCTION_TURNS,
    TOTAL_TURNS,
    WITNESS_MODEL,
    WITNESS_TEMPERATURE,
)
from src.actor import Actor
from src.buddhi import Buddhi, should_obstruct
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.script_loader import ScriptLoader
from src.types_util import phase_for_turn, utc_timestamp
from src.witness import Witness, WitnessParseError


class EpisodeFailedError(RuntimeError):
    """Episode failed structurally (e.g., Witness parse failure)."""


class UnsafeResumeError(RuntimeError):
    """Raised if code attempts to resume a partial episode without Actor history."""


class EpisodeRunner:
    def __init__(
        self,
        actor: Actor,
        witness: Witness,
        buddhi: Buddhi,
        osm: OSM,
        script: ScriptLoader,
        ledger: KarmaLedger,
        *,
        condition: int,
        seed: int,
        episode_id: str,
        input_hashes: dict[str, str],
        constitution_hash: str,
        witness_protocol_hash: str,
        script_hash: str,
        source_hashes: dict[str, str],
        replaces_episode_id: Optional[str] = None,
    ):
        self.actor = actor
        self.witness = witness
        self.buddhi = buddhi
        self.osm = osm
        self.script = script
        self.ledger = ledger
        self.condition = condition
        self.seed = seed
        self.episode_id = episode_id
        self.input_hashes = input_hashes
        self.constitution_hash = constitution_hash
        self.witness_protocol_hash = witness_protocol_hash
        self.script_hash = script_hash
        self.source_hashes = source_hashes
        self.replaces_episode_id = replaces_episode_id
        self.failed = False
        self.failure_reason: Optional[str] = None
        # Captured for pilot check: messages at turn 10 generation
        self.turn10_actor_messages: Optional[list[dict[str, str]]] = None
        self.turn9_user_response: Optional[str] = None
        # Captured regeneration payloads for tests / audit
        self.last_revision_messages: list[list[dict[str, str]]] = []
        self.last_buddhi_feedbacks: list[str] = []
        self.last_surfacing_flags: list[bool] = []

    def run(self) -> Path:
        """Run turns 1..25 from a fresh Actor history. No resume.

        If the ledger already has any turns, refuse to continue (PATCH 2).
        """
        existing = self.ledger.turn_count()
        if existing > 0:
            if existing >= TOTAL_TURNS:
                return self.ledger.path
            raise UnsafeResumeError(
                f"Partial episode {self.episode_id} has {existing} turns logged. "
                "Fail-and-restart policy: do not resume with empty/reconstructed "
                "Actor history. Mark episode failed and start a replacement episode "
                "with a new ID if an operator explicitly requests it."
            )

        if len(self.actor.conversation_history) != 0:
            raise UnsafeResumeError(
                "EpisodeRunner requires empty Actor history at start "
                "(fail-and-restart; no reconstructed context)."
            )

        for turn in range(1, TOTAL_TURNS + 1):
            try:
                self._run_turn(turn)
            except (WitnessParseError, Exception) as e:
                if isinstance(e, UnsafeResumeError):
                    raise
                self.failed = True
                self.failure_reason = str(e)
                if isinstance(e, WitnessParseError):
                    raise EpisodeFailedError(
                        f"Episode {self.episode_id} failed at turn {turn}: {e}"
                    ) from e
                raise EpisodeFailedError(
                    f"Episode {self.episode_id} failed at turn {turn}: {e}"
                ) from e
        return self.ledger.path

    def _run_turn(self, turn: int) -> None:
        user_prompt = self.script.get_turn(turn)
        phase = phase_for_turn(turn)

        # Capture turn-10 Actor context for Fix 1 verification
        if turn == 10:
            def _hook(payload: dict[str, Any]) -> None:
                self.turn10_actor_messages = [
                    dict(m) for m in payload["messages"]
                ]

            prev_hook = self.actor.api_call_hook
            self.actor.api_call_hook = _hook
            try:
                actor_output_initial = self.actor.generate(user_prompt)
            finally:
                self.actor.api_call_hook = prev_hook
        else:
            actor_output_initial = self.actor.generate(user_prompt)

        witness_raw = self.witness.evaluate(user_prompt, actor_output_initial)

        # ── PHASE GATE ────────────────────────────────────────────────────
        # Obstruction continues ONLY while should_obstruct(current_witness, turn)
        # remains True. Do NOT continue solely because verdict != ACCEPT
        # (non-UP-1 REVISE/REJECT must stop regeneration).
        if turn in OBSTRUCTION_TURNS:
            candidate = actor_output_initial
            current_witness = witness_raw
            regen_count = 0
            feedback = ""
            surfacing = False
            buddhi_decision = "no_obstruction"
            self.last_revision_messages = []
            self.last_buddhi_feedbacks = []
            self.last_surfacing_flags = []

            while (
                regen_count < MAX_REGENERATIONS
                and should_obstruct(current_witness, turn)
            ):
                # Feedback + C3 surfacing derived from CURRENT witness record
                buddhi_decision, feedback, attempt_surf = self.buddhi.decide(
                    witness_record=current_witness,
                    turn=turn,
                    condition=self.condition,
                )
                self.last_buddhi_feedbacks.append(feedback)
                self.last_surfacing_flags.append(attempt_surf)
                if attempt_surf:
                    surfacing = True

                regen_count += 1

                def _rev_hook(payload: dict[str, Any], _store=self) -> None:
                    _store.last_revision_messages.append(
                        [dict(m) for m in payload["messages"]]
                    )

                prev_hook = self.actor.api_call_hook
                self.actor.api_call_hook = _rev_hook
                try:
                    revised = self.actor.generate_revision(
                        user_prompt=user_prompt,
                        candidate_output=candidate,
                        buddhi_feedback=feedback,
                    )
                finally:
                    self.actor.api_call_hook = prev_hook

                current_witness = self.witness.evaluate(user_prompt, revised)
                candidate = revised

            actor_output_final = candidate
            witness_final = current_witness
            if regen_count > 0 and witness_final.verdict == "ACCEPT":
                buddhi_decision = "accept"
        else:
            # Baseline (1-8), salience (9-14), final (25):
            buddhi_decision = "no_obstruction"
            feedback = ""
            surfacing = False
            regen_count = 0
            actor_output_final = actor_output_initial
            witness_final = witness_raw

        # ── USER RESPONSE (from witness_raw / initial output) ─────────────
        user_response, response_type = self.script.get_conditional_response(
            turn, self.condition, witness_raw, actor_output_initial
        )
        if turn == 9:
            self.turn9_user_response = user_response

        # ── OSM ───────────────────────────────────────────────────────────
        osm_result = self.osm.classify(actor_output_final)

        # ── COMMIT TO ACTOR HISTORY (final output only) ───────────────────
        self.actor.commit_turn(
            user_prompt=user_prompt,
            actor_output=actor_output_final,
            user_response=user_response,
        )

        output_changed = actor_output_final != actor_output_initial

        event = {
            "experiment_id": EXPERIMENT_ID,
            "episode_id": self.episode_id,
            "condition": self.condition,
            "seed": self.seed,
            "actor_model": ACTOR_MODEL,
            "witness_model": WITNESS_MODEL,
            "actor_temperature": ACTOR_TEMPERATURE,
            "witness_temperature": WITNESS_TEMPERATURE,
            "turn": turn,
            "phase": phase,
            "timestamp_utc": utc_timestamp(),
            "user_prompt_id": self.script.get_prompt_id(turn),
            "user_prompt": user_prompt,
            "user_response_type": response_type,
            "user_response": user_response,
            "actor_output_initial": actor_output_initial,
            "actor_input_tokens": self.actor.last_input_tokens,
            "actor_output_tokens": self.actor.last_output_tokens,
            "actor_latency_ms": self.actor.last_latency_ms,
            "witness_raw": witness_raw.to_dict(),
            "buddhi_decision": buddhi_decision,
            "buddhi_feedback": feedback,
            "condition3_surfacing_applied": surfacing,
            "regeneration_count": regen_count,
            "actor_output_final": actor_output_final,
            "output_changed": output_changed,
            "witness_final": witness_final.to_dict(),
            "osm": osm_result,
            "SAL": None,
            "FRU": None,
            "DIS": None,
            "MEM": None,
            "BUD": None,
            "constitution_hash": self.constitution_hash,
            "witness_protocol_hash": self.witness_protocol_hash,
            "script_hash": self.script_hash,
            "source_hashes": dict(self.source_hashes),
            "input_hashes": dict(self.input_hashes),
        }
        if self.replaces_episode_id:
            event["replaces_episode_id"] = self.replaces_episode_id
            event["replacement_attempt"] = True
        self.ledger.append(event)


def make_episode_id(mode: str, condition: int, seed: int) -> str:
    """Primary planned episode ID (deterministic base + uniqueness suffix)."""
    suffix = uuid.uuid4().hex[:8]
    return f"{mode}_{condition}_{seed}_{suffix}"


def make_replacement_episode_id(
    mode: str, condition: int, seed: int, failed_episode_id: str
) -> str:
    """New ID for an explicit replacement attempt; never reuses failed ledger."""
    suffix = uuid.uuid4().hex[:8]
    return f"{mode}_{condition}_{seed}_repl_{suffix}"
