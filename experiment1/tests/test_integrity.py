"""Integrity, hash, context preflight, seed tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.experiment_config import FROZEN_MANIFEST, MODEL_CONTEXT_LIMIT
from main import context_capacity_preflight, generate_seed_manifest
from src.types_util import validate_input_integrity


def test_hashes_validated_before_episodes():
    verified = validate_input_integrity()
    assert set(verified.keys()) == set(FROZEN_MANIFEST.keys())


def test_hash_mismatch_aborts_execution(tmp_path: Path):
    with mock.patch.dict(
        "config.experiment_config.FROZEN_MANIFEST",
        {"actor_constitution_v1.md": "0" * 64},
        clear=False,
    ):
        # Patch the imported dict used by validate_input_integrity
        import src.types_util as tu

        original = dict(tu.FROZEN_MANIFEST)
        try:
            tu.FROZEN_MANIFEST["actor_constitution_v1.md"] = "0" * 64
            with pytest.raises(RuntimeError, match="HASH MISMATCH|Input integrity"):
                validate_input_integrity()
        finally:
            tu.FROZEN_MANIFEST.clear()
            tu.FROZEN_MANIFEST.update(original)


def test_context_overflow_aborts_rather_than_truncates():
    huge = "word " * 500_000
    with pytest.raises(RuntimeError, match="context exceeds"):
        context_capacity_preflight(huge, "witness", "sources")


def test_seed_manifest_exists_before_first_episode(tmp_path: Path):
    path = tmp_path / "seed_manifest.json"
    assert not path.exists()
    seeds = generate_seed_manifest(5, path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "do NOT control Claude" in data["description"] or "assignment" in data["description"].lower()
    assert set(seeds.keys()) == {"1", "2", "3"}
    assert len(seeds["1"]) == 5
    # Second call must not regenerate
    seeds2 = generate_seed_manifest(5, path)
    assert seeds2 == seeds
