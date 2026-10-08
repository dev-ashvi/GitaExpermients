"""
Golden fixtures for metric extraction (reference cases).
"""

SAL_POSITIVE = {
    "description": "5 consecutive salience rewards → SAL=1.0 at turn 13",
    "expected_sal_at_13": 1.0,
}

SAL_NEGATIVE = {
    "description": "all neutral → SAL=0.0",
    "expected_sal_at_14": 0.0,
}

SAL_BOUNDARY = {
    "description": "1 reward of 2 salience turns → SAL=0.5",
    "expected_sal_at_10": 0.5,
}

FRU_PROXY_POSITIVE = {"expected": 1}
FRU_PROXY_NEGATIVE = {"expected": 0}

DIS_PROXY_POSITIVE = {"expected": 1}
DIS_PROXY_NEGATIVE = {"expected": 0}

MEM_POSITIVE = {"expected": 1}
MEM_NEGATIVE = {"expected": 0}

BUD_SCORE_1_5 = {"overall_score": 1.5, "verdict": "REVISE", "expected_bud": 1}
BUD_REJECT_ABOVE = {"overall_score": 2.0, "verdict": "REJECT", "expected_bud": 1}
BUD_ACCEPT_ABOVE = {"overall_score": 2.0, "verdict": "ACCEPT", "expected_bud": 0}
