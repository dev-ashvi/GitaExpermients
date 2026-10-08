"""Prove frozen Experiment 1 surfaces remain intact."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))

from config.experiment_config import FROZEN_MANIFEST
from src.types_util import validate_input_integrity


# Baselines captured before Experiment 0 implementation (this session)
_EXP1_FILE_HASHES = {
    "config/experiment_config.py": "14d42aa2288dd691ab511e76bca7c0f134d5b46d32cb7f5571c4273d903d50ac",
    "main.py": "7c17823717e1936975d783ff0431734f6da33875ea7336a3d559dbaf4d7cc3f6",
    "src/actor.py": "d0ed9dd1dd26b84973275f51a1ab49c8bdb499b599130627c6c5b78e62badbb6",
    "src/witness.py": "644daf98c82f070b5f389da09de704eca01c6b2c0e79d21cffa78b94f372590f",
    "src/episode_runner.py": "078fdb1aa19e1a34582be4469aded1465ba3f9ebc3604591774d7fb20abd7cf2",
    "src/buddhi.py": "56b06f535aa670069ae0473d9c9abb13244f2842978ee3a4b6df6e49ea5b4821",
    "src/script_loader.py": "c54f99926671a21df2072beb653d66a7b5c5298fd38040abab6547fdfe5bbd3d",
    "OPEN_ISSUES.md": "b887e90ce8876a621e19c7275de42191bd56fb83bc593ce3883349de6abc4dd1",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_experiment1_critical_files_byte_unchanged():
    for rel, expected in _EXP1_FILE_HASHES.items():
        actual = _sha256(EXP1 / rel)
        assert actual == expected, f"{rel} changed: {actual} != {expected}"


def test_frozen_manifest_still_validates():
    verified = validate_input_integrity()
    assert set(verified.keys()) == set(FROZEN_MANIFEST.keys())


def test_no_experiment0_outputs_in_experiment1_runs():
    runs = EXP1 / "runs"
    if not runs.exists():
        return
    # No exp0 episode ledgers under experiment1/runs
    bad = list(runs.rglob("*experiment-0*")) + list(runs.rglob("*exp0*"))
    assert bad == []
