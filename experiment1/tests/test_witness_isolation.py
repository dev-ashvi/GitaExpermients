"""Witness isolation tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import DOCUMENTS_DIR
from src.types_util import build_source_packet, load_text
from src.witness import Witness, WitnessIsolationError, WitnessParseError
from tests.conftest import MockAnthropic, default_responder, make_witness_payload
import json


def test_witness_request_contains_no_condition_phase_turn_prior_verdict_leakage():
    protocol = load_text(DOCUMENTS_DIR / "witness_protocol_v1.md")
    sources = build_source_packet()
    client = MockAnthropic(default_responder)
    captured = []

    def hook(payload):
        captured.append(payload)

    w = Witness(client, protocol, sources, api_call_hook=hook)
    w.evaluate("What about weight?", "Evidence is mixed and uncertain.")
    assert captured
    user_content = captured[0]["user_content"]
    for label in (
        "CONDITION:",
        "PHASE:",
        "TURN NUMBER:",
        "OSM:",
        "PRIOR WITNESS",
        "BUDDHI:",
        "HYPOTHESIS:",
    ):
        assert label not in user_content.upper()
    assert "condition=1" not in user_content
    assert "turn 9" not in user_content.lower()


def test_witness_never_receives_osm_or_condition_information():
    protocol = load_text(DOCUMENTS_DIR / "witness_protocol_v1.md")
    sources = build_source_packet()
    msg = Witness(None, protocol, sources).build_eval_user_message(
        "user q", "actor out"
    )
    assert "osm" not in msg.lower() or "osm" in sources.lower()
    # Builder itself must not inject harness condition/metadata labels.
    # Do not ban incidental scientific wording (e.g. "experimental") from sources.
    assert "CONDITION" not in msg
    assert "experimental condition" not in msg.lower()
    assert "PHASE:" not in msg.upper()
    assert "BUDDHI:" not in msg.upper()


def test_witness_strict_json_no_silent_defaults():
    protocol = load_text(DOCUMENTS_DIR / "witness_protocol_v1.md")
    sources = build_source_packet()

    def bad_responder(_kwargs):
        return "not json at all"

    client = MockAnthropic(bad_responder)
    w = Witness(client, protocol, sources)
    with pytest.raises(WitnessParseError):
        w.evaluate("q", "a")


def test_witness_accepts_valid_json():
    protocol = load_text(DOCUMENTS_DIR / "witness_protocol_v1.md")
    sources = build_source_packet()

    def ok(_kwargs):
        return json.dumps(make_witness_payload())

    client = MockAnthropic(ok)
    w = Witness(client, protocol, sources)
    rec = w.evaluate("q", "a")
    assert rec.verdict == "ACCEPT"
