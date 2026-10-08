"""Generate CONDITION_DIFF_REPORT.md programmatically."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import UP1_FROZEN, UP5_FROZEN
from src.buddhi import Buddhi, should_obstruct
from src.script_loader import (
    OBSTRUCTION_NEUTRAL_RESPONSE,
    TURN_PROMPTS,
    ScriptLoader,
)
from src.types_util import WitnessRecord
from tests.conftest import up1_revise_payload


def build_report() -> str:
    script = ScriptLoader()
    lines = [
        "# CONDITION_DIFF_REPORT",
        "",
        "Programmatic demonstration of allowed condition differences.",
        "Generated from frozen harness modules (no LLM calls).",
        "",
        "## C1 vs C2: difference only in turns 9–14 user responses",
        "",
        "| Turn | Prompt identical? | C1 (UP-1 present) | C2 |",
        "|------|-------------------|-------------------|-----|",
    ]
    up1 = WitnessRecord.from_dict(up1_revise_payload())
    for turn in range(1, 26):
        p1 = script.get_turn(turn)
        assert p1 == TURN_PROMPTS[turn]
        r1, t1 = script.get_conditional_response(turn, 1, up1)
        r2, t2 = script.get_conditional_response(turn, 2, up1)
        if turn in range(9, 15):
            assert t2 == "neutral"
            assert t1 == "reward"
            assert r1 != r2
            diff = f"C1={t1} / C2={t2}"
        else:
            assert r1 == r2 and t1 == t2 == "neutral"
            if turn in range(15, 25):
                assert r1 == OBSTRUCTION_NEUTRAL_RESPONSE
            diff = "identical neutral"
        lines.append(f"| {turn} | YES | {t1} | {diff} |")

    lines.extend(
        [
            "",
            "### Conclusion (C1 vs C2)",
            "",
            "- User prompts: identical for all 25 turns.",
            "- User responses: differ only on turns 9–14 (reward/pressure vs neutral).",
            f"- Turns 15–24 user responses: identical frozen neutral "
            f"`{OBSTRUCTION_NEUTRAL_RESPONSE}` across all conditions.",
            "- Turn 25: empty user response (None).",
            "- Buddhi/OSM/Witness/Actor models: identical.",
            "",
            "## C1 vs C3: identical through turn 14; obstruction differs only by UP-1/UP-5 surfacing",
            "",
            "| Turn | Response identical (UP-1)? | Surfacing C1 | Surfacing C3 (should_obstruct) |",
            "|------|----------------------------|--------------|--------------------------------|",
        ]
    )
    b = Buddhi()
    for turn in range(1, 26):
        r1, t1 = script.get_conditional_response(turn, 1, up1)
        r3, t3 = script.get_conditional_response(turn, 3, up1)
        resp_same = "YES" if r1 == r3 else "NO"
        d1, f1, s1 = b.decide(up1, turn=turn, condition=1)
        d3, f3, s3 = b.decide(up1, turn=turn, condition=3)
        lines.append(
            f"| {turn} | {resp_same} | {s1} (decision={d1}) | {s3} (decision={d3}) |"
        )
        if turn <= 14:
            assert r1 == r3
            assert s1 is False and s3 is False
        if turn in range(15, 25):
            assert should_obstruct(up1, turn)
            assert s1 is False
            assert s3 is True
            assert UP1_FROZEN in f3 and UP5_FROZEN in f3
            assert UP1_FROZEN not in f1
            assert f1 in f3

    lines.extend(
        [
            "",
            "### Frozen surfacing text (Condition 3 only)",
            "",
            "```",
            UP1_FROZEN,
            "```",
            "",
            "```",
            UP5_FROZEN,
            "```",
            "",
            "### Conclusion (C1 vs C3)",
            "",
            "- Through turn 14: user prompts, user responses, and Buddhi behavior identical.",
            "- Turns 15–24: Buddhi differs only by verbatim UP1_FROZEN + UP5_FROZEN when "
            "`should_obstruct(...)` is True; user responses identical.",
            "- Turn 25: identical (no obstruction).",
            "",
        ]
    )
    return "\n".join(lines)


def test_generate_condition_diff_report():
    report = build_report()
    out = ROOT / "CONDITION_DIFF_REPORT.md"
    out.write_text(report, encoding="utf-8")
    assert "C1 vs C2" in report
    assert "Understood. Please continue." in report
    assert "Constitutional requirement UP-1" in report
