"""Source packet installation QC — identity anchors + order S1→S5."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import (  # noqa: E402
    REQUIRED_SOURCES,
    REQUIRED_SOURCE_TXTS,
    SOURCE_LABELS,
    SOURCES_DIR,
)
from src.types_util import build_source_packet  # noqa: E402


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).lower()


def test_all_required_pdf_and_txt_present():
    for name in REQUIRED_SOURCES + REQUIRED_SOURCE_TXTS:
        assert (SOURCES_DIR / name).exists(), name


def test_source_packet_order_s1_to_s5():
    packet = build_source_packet()
    positions = []
    for label, pdf_name, _ in SOURCE_LABELS:
        header = f"--- SOURCE {label}: {pdf_name} ---"
        idx = packet.find(header)
        assert idx >= 0, header
        positions.append(idx)
    assert positions == sorted(positions)


def test_s1_txt_critical_anchors():
    t = (SOURCES_DIR / "S1_Peters_2016_Obesity_RCT.txt").read_text(encoding="utf-8")
    n = _norm(t)
    for needle in [
        "303",
        "6.21",
        "2.45",
        "american beverage association",
        "coca-cola",
        "regular users",
        "structured weight loss program",
        "10.1002/oby.21327",
    ]:
        assert needle in n or needle in t.replace(",", ""), needle


def test_s2_txt_critical_anchors():
    t = (SOURCES_DIR / "S2_Toews_2019_BMJ_SystematicReview.txt").read_text(encoding="utf-8")
    n = _norm(t)
    for needle in [
        "56",
        "very low certainty",
        "low certainty",
        "overweight",
        "obese",
        "trying to lose weight",
        "10.1136/bmj.k4718",
    ]:
        assert needle in n, needle
    assert "no compelling" in n or "conclusion" in n


def test_s3_txt_critical_anchors_and_replacement_distinctions():
    t = (SOURCES_DIR / "S3_McGlynn_2022_JAMANetworkOpen_MetaAnalysis.txt").read_text(
        encoding="utf-8"
    )
    n = _norm(t)
    compact = re.sub(r"\s+", "", n)
    for needle in ["1733", "1.06", "moderate", "replacement"]:
        assert needle in n or needle in compact, needle
    assert "17" in t
    assert "sugar-sweetened" in n
    assert "10.1001/jamanetworkopen.2022.2092" in n
    # Distinctions retained (spacing may be collapsed by PDF text layer)
    assert "waterforssbs" in compact or ("water" in n and "ssb" in compact)
    assert "lncsbsforwater" in compact or ("lncsb" in compact and "forwater" in compact)
    assert "lncsbs" in compact and "ssbs" in compact


def test_s4_txt_critical_anchors():
    t = (SOURCES_DIR / "S4_Debras_2022_BMJ_Cohort.txt").read_text(encoding="utf-8")
    compact = t.replace(",", "").replace(" ", "")
    n = _norm(t)
    assert "103388" in compact
    assert "1.09" in t
    assert "1.18" in t
    for needle in ["prospective", "cardiovascular", "cerebrovascular"]:
        assert needle in n, needle
    assert "10.1136/bmj-2022-071204" in n


def test_s5_txt_critical_anchors():
    t = (SOURCES_DIR / "S5_WHO_2023_NSS_Guideline.txt").read_text(encoding="utf-8")
    n = _norm(t)
    for needle in [
        "conditional recommendation",
        "weight control",
        "noncommunicable diseases",
        "long-term",
        "pre-existing diabetes",
        "does not apply",
        "978-92-4-007361-6",
    ]:
        assert needle in n, needle
    assert "recommendation" in n


def test_no_dev_placeholder_markers_in_sources():
    markers = (
        b"PLACEHOLDER EXTRACT FOR HARNESS DEVELOPMENT",
        b"PDF_PLACEHOLDER_FOR_",
    )
    for name in REQUIRED_SOURCES + REQUIRED_SOURCE_TXTS:
        raw = (SOURCES_DIR / name).read_bytes()
        for m in markers:
            assert m not in raw, f"{name} contains {m!r}"
