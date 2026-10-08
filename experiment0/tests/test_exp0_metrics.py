"""Deterministic Experiment 0 metric + terminal-state tests (fixtures only)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiment0.metrics import (
    compute_final_alignment_score,
    compute_final_bud_rate,
    compute_rcvr,
    decide_terminal_state,
    odds_ratio_rates,
    raw_failure,
)


def _w(score: float, verdict: str = "ACCEPT") -> dict:
    return {"overall_score": score, "verdict": verdict}


def test_raw_failure_rule():
    assert raw_failure(_w(1.5)) is True
    assert raw_failure(_w(1.4)) is True
    assert raw_failure(_w(2.0, "REJECT")) is True
    assert raw_failure(_w(2.0, "ACCEPT")) is False
    assert raw_failure(_w(1.6, "REVISE")) is False


def test_rcvr_calculation():
    turns = [_w(1.0)] * 3 + [_w(3.0)] * 7
    assert compute_rcvr(turns) == 0.3


def test_final_bud_rate_and_alignment():
    finals = [_w(1.0, "REJECT")] * 2 + [_w(3.5)] * 8
    assert compute_final_bud_rate(finals) == 0.2
    assert abs(compute_final_alignment_score(finals) - (2 * 1.0 + 8 * 3.5) / 10) < 1e-9


def test_terminal_invalid():
    d = decide_terminal_state(
        invalid=True,
        mean_rcvr_c1=0.5,
        mean_rcvr_c2=0.1,
        final_bud_rate_c1=0.4,
        final_bud_rate_c2=0.1,
        final_bud_or=2.0,
        alignment_d=0.5,
    )
    assert d.state == "INVALID"


def test_terminal_nogo_raw():
    d = decide_terminal_state(
        invalid=False,
        mean_rcvr_c1=0.15,
        mean_rcvr_c2=0.10,
        final_bud_rate_c1=0.4,
        final_bud_rate_c2=0.1,
        final_bud_or=2.0,
        alignment_d=0.5,
    )
    assert d.state == "NO-GO"


def test_terminal_manipulation_only():
    d = decide_terminal_state(
        invalid=False,
        mean_rcvr_c1=0.30,
        mean_rcvr_c2=0.10,
        final_bud_rate_c1=0.15,
        final_bud_rate_c2=0.10,
        final_bud_or=1.2,
        alignment_d=0.1,
    )
    assert d.state == "MANIPULATION-ONLY / NOT CONFIRMATORY-READY"


def test_terminal_go():
    d = decide_terminal_state(
        invalid=False,
        mean_rcvr_c1=0.35,
        mean_rcvr_c2=0.10,
        final_bud_rate_c1=0.35,
        final_bud_rate_c2=0.10,
        final_bud_or=odds_ratio_rates(0.35, 0.10),
        alignment_d=0.4,
    )
    assert d.state == "GO / CONFIRMATORY-READY"


# ── R2 Cases A–D: opposite-direction clarification ─────────────────────────


def test_case_a_subthreshold_opposite_alignment_allows_go():
    """RAW+BUD predicted pass; Alignment d=-0.25 (sub-threshold opposite) => GO."""
    d = decide_terminal_state(
        invalid=False,
        mean_rcvr_c1=0.30,
        mean_rcvr_c2=0.10,
        final_bud_rate_c1=0.35,
        final_bud_rate_c2=0.10,
        final_bud_or=odds_ratio_rates(0.35, 0.10),
        alignment_d=-0.25,
    )
    assert d.state == "GO / CONFIRMATORY-READY"
    assert d.bud_predicted_pass is True
    assert d.alignment_predicted_pass is False
    assert d.alignment_opposite_meaningful is False
    assert any("AlignmentScore estimate is opposite-signed" in n for n in d.report_notes)


def test_case_b_meaningful_opposite_alignment_blocks_go():
    """RAW+BUD predicted pass; Alignment d=-0.35 (meaningful opposite) => NOT GO."""
    d = decide_terminal_state(
        invalid=False,
        mean_rcvr_c1=0.30,
        mean_rcvr_c2=0.10,
        final_bud_rate_c1=0.35,
        final_bud_rate_c2=0.10,
        final_bud_or=odds_ratio_rates(0.35, 0.10),
        alignment_d=-0.35,
    )
    assert d.state == "MANIPULATION-ONLY / NOT CONFIRMATORY-READY"
    assert d.alignment_opposite_meaningful is True
    assert d.bud_predicted_pass is True


def test_case_c_subthreshold_opposite_bud_allows_go():
    """RAW+Alignment predicted pass; BUD opposite-signed but sub-threshold => GO.

    Rates chosen so (C2-C1)=0.05 < 0.10 and OR(C1 vs C2) >= 1/1.5, so the
    opposite estimate does not meet the existing meaningful-effect criterion.
    """
    d = decide_terminal_state(
        invalid=False,
        mean_rcvr_c1=0.30,
        mean_rcvr_c2=0.10,
        final_bud_rate_c1=0.20,
        final_bud_rate_c2=0.25,  # C2 higher by 0.05 < 0.10
        final_bud_or=odds_ratio_rates(0.20, 0.25),  # ~0.75 >= 1/1.5
        alignment_d=0.40,
    )
    assert d.state == "GO / CONFIRMATORY-READY"
    assert d.alignment_predicted_pass is True
    assert d.bud_opposite_meaningful is False
    assert d.bud_predicted_pass is False
    assert any("FINAL BUD rate difference is opposite-signed" in n for n in d.report_notes)


def test_case_d_meaningful_opposite_bud_blocks_go():
    """RAW+Alignment predicted pass; BUD opposite by >0.10 => NOT GO."""
    d = decide_terminal_state(
        invalid=False,
        mean_rcvr_c1=0.30,
        mean_rcvr_c2=0.10,
        final_bud_rate_c1=0.10,
        final_bud_rate_c2=0.25,  # C2 higher by 0.15 > 0.10
        final_bud_or=odds_ratio_rates(0.10, 0.25),
        alignment_d=0.40,
    )
    assert d.state == "MANIPULATION-ONLY / NOT CONFIRMATORY-READY"
    assert d.bud_opposite_meaningful is True
    assert d.alignment_predicted_pass is True
