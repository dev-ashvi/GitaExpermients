"""PATCH 6 / ISSUE-006 — real sources required; placeholders hard-block."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.types_util import (  # noqa: E402
    SOURCE_PLACEHOLDER_MARKERS,
    assert_sources_not_placeholders,
    validate_input_integrity,
)


def test_hashes_validate_for_current_files():
    verified = validate_input_integrity()
    assert len(verified) > 0


def test_installed_sources_are_not_placeholders():
    """ISSUE-006 resolved: production sources must pass the placeholder scan."""
    assert_sources_not_placeholders()


def test_placeholder_markers_still_block_when_present(tmp_path, monkeypatch):
    """Regression: if placeholder markers reappear, production must hard-fail."""
    import src.types_util as tu
    from config.experiment_config import REQUIRED_SOURCE_TXTS, REQUIRED_SOURCES

    fake = tmp_path / "sources"
    fake.mkdir()
    for name in list(REQUIRED_SOURCES) + list(REQUIRED_SOURCE_TXTS):
        (fake / name).write_bytes(b"PDF_PLACEHOLDER_FOR_TEST\nPLACEHOLDER EXTRACT\n")

    monkeypatch.setattr(tu, "SOURCES_DIR", fake)
    with pytest.raises(RuntimeError, match="Placeholder|placeholder|Real scientific"):
        assert_sources_not_placeholders()


def test_placeholder_marker_constants_unchanged():
    assert "PDF_PLACEHOLDER_FOR_" in SOURCE_PLACEHOLDER_MARKERS
    assert "PLACEHOLDER EXTRACT FOR HARNESS DEVELOPMENT" in SOURCE_PLACEHOLDER_MARKERS
