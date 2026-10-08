"""Experiment 0 episode runner — frozen protocol, NIM provider.

Mirrors Experiment 1 turn order without modifying Experiment 1 sources.
Fail-and-restart within an episode; completed episodes are never re-run.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
EXP1 = REPO / "experiment1"
if str(EXP1) not in sys.path:
    sys.path.insert(0, str(EXP1))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.retry_amendment import TerminalOperationalError
from experiment0.script_loader import Experiment0ScriptLoader
from src.actor import Actor
from src.buddhi import Buddhi, should_obstruct
from src.karma_ledger import KarmaLedger
from src.osm import OSM
from src.types_util import phase_for_turn, utc_timestamp
from src.witness import Witness, WitnessParseError

e0 = load_experiment0_config()


class EpisodeFailedError(RuntimeError):
    pass


class UnsafeResumeError(RuntimeError):
    pass


class Experiment0EpisodeRunner:
    def __init__(
        self,
        actor: Actor,
        witness: Witness,
        buddhi: Buddhi,
        osm: OSM,
        script: Experiment0ScriptLoader,
        ledger: KarmaLedger,
        *,
        condition: int,
        seed: int,
        episode_id: str,
        run_id: str,
        input_hashes: dict[str, str],
        constitution_hash: str,
        witness_protocol_hash: str,
        script_hash: str,
        source_hashes: dict[str, str],
        schedule_index: int,
    ):
        if condition not in (1, 2):
            raise ValueError(f"Experiment 0 supports C1/C2 only; got {condition}")
        self.actor = actor
        self.witness = witness
        self.buddhi = buddhi
        self.osm = osm
        self.script = script
        self.ledger = ledger
        self.condition = condition
        self.seed = seed
        self.episode_id = episode_id
        self.run_id = run_id
        self.input_hashes = input_hashes
        self.constitution_hash = constitution_hash
        self.witness_protocol_hash = witness_protocol_hash
        self.script_hash = script_hash
        self.source_hashes = source_hashes
        self.schedule_index = schedule_index
        self.failed = False
        self.failure_reason: Optional[str] = None
        self.turn9_user_response: Optional[str] = None

    def run(self) -> Path:
        existing = self.ledger.turn_count()
        if existing > 0:
            if existing >= e0.TOTAL_TURNS:
                return self.ledger.path
            raise UnsafeResumeError(
                f"Partial episode {self.episode_id} has {existing} turns. "
                "Fail-and-restart: do not resume mid-episode."
            )
        if len(self.actor.conversation_history) != 0:
            raise UnsafeResumeError(
                "Experiment0EpisodeRunner requires empty Actor history at start."
            )

        for turn in range(1, e0.TOTAL_TURNS + 1):
            try:
                self._run_turn(turn)
            except UnsafeResumeError:
                raise
            except TerminalOperationalError as exc:
                # Must not be absorbed into generic Exception handling upstream of
                # Actor/Witness — re-raise as EpisodeFailedError carrying ops class.
                self.failed = True
                self.failure_reason = (
                    f"terminal_ops:{exc.failure_class}:{exc}"
                )
                raise EpisodeFailedError(
                    f"Episode {self.episode_id} operational stop at turn {turn}: "
                    f"[{exc.failure_class}] {exc}"
                ) from exc
            except KeyboardInterrupt:
                # Operator interrupt — never rewrite as operational/scientific fail.
                raise
            except (WitnessParseError, Exception) as exc:
                # WitnessParseError keeps frozen scientific retry semantics inside
                # Witness.evaluate; reaching here means retries exhausted.
                self.failed = True
                self.failure_reason = str(exc)
                raise EpisodeFailedError(
                    f"Episode {self.episode_id} failed at turn {turn}: {exc}"
                ) from exc
            # Unexpected BaseException subclasses must propagate uncaught.
        return self.ledger.path

    def _provider_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for client in (self.actor.client, self.witness.client):
            norm = getattr(client, "last_normalized", None)
            if norm is not None:
                meta = {
                    "finish_reason": norm.finish_reason,
                    "prompt_tokens": norm.prompt_tokens,
                    "completion_tokens": norm.completion_tokens,
                    "retries": norm.retries,
                    "model_id_returned": norm.model_id_returned,
                    "latency_ms": norm.latency_ms,
                }
        return meta

    def _run_turn(self, turn: int) -> None:
        user_prompt = self.script.get_turn(turn)
        phase = phase_for_turn(turn)

        actor_output_initial = self.actor.generate(user_prompt)
        witness_raw = self.witness.evaluate(user_prompt, actor_output_initial)

        obstruction_turns = set(e0.OBSTRUCTION_TURNS)
        if turn in obstruction_turns:
            candidate = actor_output_initial
            current_witness = witness_raw
            regen_count = 0
            feedback = ""
            surfacing = False
            buddhi_decision = "no_obstruction"

            while (
                regen_count < e0.MAX_REGENERATIONS
                and should_obstruct(current_witness, turn)
            ):
                buddhi_decision, feedback, attempt_surf = self.buddhi.decide(
                    witness_record=current_witness,
                    turn=turn,
                    condition=self.condition,
                )
                if attempt_surf:
                    surfacing = True
                regen_count += 1
                revised = self.actor.generate_revision(
                    user_prompt=user_prompt,
                    candidate_output=candidate,
                    buddhi_feedback=feedback,
                )
                current_witness = self.witness.evaluate(user_prompt, revised)
                candidate = revised

            actor_output_final = candidate
            witness_final = current_witness
            if regen_count > 0 and witness_final.verdict == "ACCEPT":
                buddhi_decision = "accept"
        else:
            buddhi_decision = "no_obstruction"
            feedback = ""
            surfacing = False
            regen_count = 0
            actor_output_final = actor_output_initial
            witness_final = witness_raw

        user_response, response_type = self.script.get_conditional_response(
            turn, self.condition, witness_raw, actor_output_initial
        )
        if turn == 9:
            self.turn9_user_response = user_response

        osm_result = self.osm.classify(actor_output_final)
        self.actor.commit_turn(
            user_prompt=user_prompt,
            actor_output=actor_output_final,
            user_response=user_response,
        )
        output_changed = actor_output_final != actor_output_initial

        event = {
            "experiment_id": e0.EXPERIMENT_ID,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "schedule_index": self.schedule_index,
            "condition": self.condition,
            "seed": self.seed,
            "actor_model": e0.ACTOR_MODEL,
            "witness_model": e0.WITNESS_MODEL,
            "actor_temperature": e0.ACTOR_TEMPERATURE,
            "witness_temperature": e0.WITNESS_TEMPERATURE,
            "max_tokens_actor": e0.MAX_TOKENS_ACTOR,
            "max_tokens_witness": e0.MAX_TOKENS_WITNESS,
            "enable_thinking": e0.ENABLE_THINKING,
            "provider": "nvidia-nim",
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
            "provider_meta": self._provider_meta(),
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
        self.ledger.append(event)


def make_episode_id(*, run_id: str, condition: int, seed: int, schedule_index: int) -> str:
    suffix = uuid.uuid4().hex[:8]
    return f"e0_{run_id}_c{condition}_s{seed}_i{schedule_index:02d}_{suffix}"
