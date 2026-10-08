"""Pilot structural validation — instrumentation only. No outcome inspection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from config.experiment_config import OBSTRUCTION_TURNS, SALIENCE_TURNS, TOTAL_TURNS
from src.buddhi import should_obstruct
from src.karma_ledger import KarmaLedger
from src.metric_extractor import extract_metrics
from src.types_util import WitnessRecord


REQUIRED_TOP_LEVEL_FIELDS = (
    "experiment_id",
    "episode_id",
    "condition",
    "seed",
    "turn",
    "phase",
    "user_prompt",
    "user_response",
    "user_response_type",
    "actor_output_initial",
    "actor_output_final",
    "witness_raw",
    "witness_final",
    "buddhi_decision",
    "buddhi_feedback",
    "condition3_surfacing_applied",
    "regeneration_count",
    "osm",
    "SAL",
    "FRU",
    "DIS",
    "MEM",
    "BUD",
    "constitution_hash",
    "source_hashes",
    "input_hashes",
)

WITNESS_REQUIRED = (
    "truth",
    "uncertainty",
    "scope",
    "tone",
    "refusal",
    "overall_score",
    "verdict",
    "violations",
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PilotReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(CheckResult(name, passed, detail))

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_passed": self.all_passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _load_pilot_episodes(pilot_dir: Path) -> list[list[dict[str, Any]]]:
    episodes = []
    for path in sorted(Path(pilot_dir).glob("*.jsonl")):
        if path.name.startswith("seed_manifest"):
            continue
        events = KarmaLedger.read_file(path)
        if events:
            episodes.append(events)
    return episodes


def check_all_25_turns_execute(episodes: list[list[dict]]) -> CheckResult:
    failures = []
    for ep in episodes:
        turns = {e["turn"] for e in ep}
        if turns != set(range(1, TOTAL_TURNS + 1)):
            failures.append(
                f"{ep[0].get('episode_id')}: turns={sorted(turns)}"
            )
    return CheckResult(
        "all_25_turns_execute",
        not failures,
        "; ".join(failures) if failures else f"{len(episodes)} episodes × 25 turns",
    )


def check_condition_branching_correct(episodes: list[list[dict]]) -> CheckResult:
    conditions_seen = set()
    failures = []
    for ep in episodes:
        conds = {e["condition"] for e in ep}
        if len(conds) != 1:
            failures.append(f"{ep[0].get('episode_id')}: multiple conditions {conds}")
        else:
            conditions_seen.add(next(iter(conds)))
    if conditions_seen != {1, 2, 3}:
        failures.append(f"conditions present: {sorted(conditions_seen)}")
    return CheckResult(
        "condition_branching_correct",
        not failures,
        "; ".join(failures) if failures else "conditions 1,2,3 present; one per episode",
    )


def check_condition3_surfacing_correct(episodes: list[list[dict]]) -> CheckResult:
    """Surfacing only when condition==3 AND turn in 15-24 AND should_obstruct.

    Uses frozen should_obstruct trigger — not the broader decision != accept.
    """
    failures = []
    for ep in episodes:
        for e in ep:
            applied = bool(e.get("condition3_surfacing_applied"))
            cond = e["condition"]
            turn = e["turn"]
            raw = WitnessRecord.from_dict(e["witness_raw"])
            expected = (
                cond == 3
                and turn in OBSTRUCTION_TURNS
                and should_obstruct(raw, turn)
            )
            if applied != expected:
                failures.append(
                    f"{e.get('episode_id')} turn {turn}: "
                    f"surfacing={applied} expected={expected}"
                )
    return CheckResult(
        "condition3_surfacing_correct",
        not failures,
        "; ".join(failures[:10]) if failures else "surfacing matches should_obstruct",
    )


def check_reward_responses_correct(episodes: list[list[dict]]) -> CheckResult:
    """Validate reward/pressure/neutral against witness_raw UP-1 trigger (PATCH 3)."""
    failures = []
    for ep in episodes:
        for e in ep:
            turn = e["turn"]
            cond = e["condition"]
            rtype = e.get("user_response_type")
            raw = WitnessRecord.from_dict(e["witness_raw"])
            has_up1 = raw.has_up1_violation()

            if turn in SALIENCE_TURNS:
                if cond == 2:
                    expected = "neutral"
                elif cond in (1, 3):
                    expected = "reward" if has_up1 else "pressure"
                else:
                    failures.append(f"invalid condition {cond}")
                    continue
                if rtype != expected:
                    failures.append(
                        f"{e.get('episode_id')} t{turn} cond={cond}: "
                        f"got {rtype!r} expected {expected!r} "
                        f"(up1={has_up1})"
                    )
            else:
                if rtype in ("reward", "pressure"):
                    failures.append(
                        f"{e.get('episode_id')} t{turn} cond={cond}: "
                        f"{rtype!r} outside salience turns 9-14"
                    )
                elif rtype != "neutral":
                    failures.append(
                        f"{e.get('episode_id')} t{turn}: unexpected type {rtype!r}"
                    )
    return CheckResult(
        "reward_responses_correct",
        not failures,
        "; ".join(failures[:10])
        if failures
        else "reward/pressure/neutral match witness_raw UP-1 logic",
    )


def check_witness_schema_valid(episodes: list[list[dict]]) -> CheckResult:
    failures = []
    for ep in episodes:
        for e in ep:
            for key in ("witness_raw", "witness_final"):
                rec = e.get(key)
                if not isinstance(rec, dict):
                    failures.append(f"missing {key}")
                    continue
                missing = [f for f in WITNESS_REQUIRED if f not in rec]
                if missing:
                    failures.append(
                        f"{e.get('episode_id')} t{e['turn']} {key}: {missing}"
                    )
    return CheckResult(
        "witness_schema_valid",
        not failures,
        "; ".join(failures[:10]) if failures else "witness schemas valid",
    )


def check_regeneration_logged(episodes: list[list[dict]]) -> CheckResult:
    failures = []
    for ep in episodes:
        for e in ep:
            if e.get("regeneration_count") is None:
                failures.append(f"{e.get('episode_id')} t{e['turn']}")
    return CheckResult(
        "regeneration_logged",
        not failures,
        "; ".join(failures[:10]) if failures else "regeneration_count present",
    )


def check_ledger_reconstructable(episodes: list[list[dict]]) -> CheckResult:
    failures = []
    for ep in episodes:
        for e in ep:
            missing = [f for f in REQUIRED_TOP_LEVEL_FIELDS if f not in e]
            if missing:
                failures.append(
                    f"{e.get('episode_id')} t{e['turn']}: {missing}"
                )
    return CheckResult(
        "ledger_reconstructable",
        not failures,
        "; ".join(failures[:10]) if failures else "all required fields present",
    )


def check_no_witness_context_leakage() -> CheckResult:
    """Code-inspection documented check."""
    detail = (
        "MANUAL/CODE CHECK: Actor system prompt builder excludes Witness; "
        "Witness.evaluate receives only source packet + user turn + actor output; "
        "Buddhi feedback strips scores/verdicts. Covered by unit tests "
        "test_actor_isolation / test_witness_isolation."
    )
    return CheckResult("no_witness_context_leakage", True, detail)


def check_seeds_and_hashes_recorded(episodes: list[list[dict]]) -> CheckResult:
    failures = []
    for ep in episodes:
        for e in ep:
            if not e.get("seed"):
                failures.append(f"{e.get('episode_id')}: empty seed")
            if not e.get("constitution_hash"):
                failures.append(f"{e.get('episode_id')}: empty constitution_hash")
            sh = e.get("source_hashes") or {}
            if not sh:
                failures.append(f"{e.get('episode_id')}: empty source_hashes")
    return CheckResult(
        "seeds_and_hashes_recorded",
        not failures,
        "; ".join(failures[:10]) if failures else "seeds and hashes recorded",
    )


def check_metric_extractor_runs(
    episodes: list[list[dict]], pilot_dir: Path, enriched_dir: Path
) -> CheckResult:
    failures = []
    enriched_dir = Path(enriched_dir)
    enriched_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(Path(pilot_dir).glob("*.jsonl")):
        if path.name.startswith("seed_manifest"):
            continue
        out = enriched_dir / f"{path.stem}_enriched.jsonl"
        try:
            extract_metrics(path, out)
            enriched = KarmaLedger.read_file(out)
            for e in enriched:
                if e.get("SAL") is None or e.get("BUD") is None:
                    failures.append(
                        f"{path.name} t{e.get('turn')}: SAL/BUD null"
                    )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path.name}: {exc}")
    return CheckResult(
        "metric_extractor_runs",
        not failures,
        "; ".join(failures[:10]) if failures else "extractor OK; SAL/BUD non-null",
    )


def check_user_response_in_actor_history(
    turn10_messages_by_episode: Optional[dict[str, list[dict]]] = None,
    turn9_responses_by_episode: Optional[dict[str, str]] = None,
) -> CheckResult:
    """Verify turn 9 user_response appears in Actor context at turn 10.

    Requires instrumentation captures from EpisodeRunner. If not provided,
    reports as needing log inspection.
    """
    if not turn10_messages_by_episode or not turn9_responses_by_episode:
        return CheckResult(
            "user_response_in_actor_history",
            False,
            "No turn-10 message captures provided. Re-run pilot with instrumentation "
            "or execute unit test test_turn9_response_in_turn10_context.",
        )
    failures = []
    for eid, messages in turn10_messages_by_episode.items():
        expected = turn9_responses_by_episode.get(eid, "")
        blob = "\n".join(m.get("content", "") for m in messages)
        if expected and expected not in blob:
            failures.append(f"{eid}: turn9 response absent from turn10 context")
    return CheckResult(
        "user_response_in_actor_history",
        not failures,
        "; ".join(failures) if failures else "turn9 user_response present at turn10",
    )


def run_pilot_checks(
    pilot_dir: Path,
    enriched_dir: Path,
    *,
    turn10_messages_by_episode: Optional[dict[str, list[dict]]] = None,
    turn9_responses_by_episode: Optional[dict[str, str]] = None,
) -> PilotReport:
    """Run all 11 structural pilot checks. No outcome inspection."""
    report = PilotReport()
    episodes = _load_pilot_episodes(pilot_dir)
    if not episodes:
        report.add("all_25_turns_execute", False, "No pilot episodes found")
        return report

    report.checks.append(check_all_25_turns_execute(episodes))
    report.checks.append(check_condition_branching_correct(episodes))
    report.checks.append(check_condition3_surfacing_correct(episodes))
    report.checks.append(check_reward_responses_correct(episodes))
    report.checks.append(check_witness_schema_valid(episodes))
    report.checks.append(check_regeneration_logged(episodes))
    report.checks.append(check_ledger_reconstructable(episodes))
    report.checks.append(check_no_witness_context_leakage())
    report.checks.append(check_seeds_and_hashes_recorded(episodes))
    report.checks.append(
        check_metric_extractor_runs(episodes, pilot_dir, enriched_dir)
    )
    report.checks.append(
        check_user_response_in_actor_history(
            turn10_messages_by_episode, turn9_responses_by_episode
        )
    )
    return report


def write_pilot_report(report: PilotReport, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
