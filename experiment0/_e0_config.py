"""Load repository config/experiment0_config.py without shadowing Exp1's config package."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_REPO = Path(__file__).resolve().parent.parent
_CFG_PATH = _REPO / "config" / "experiment0_config.py"


def load_experiment0_config() -> ModuleType:
    name = "experiment0_config"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _CFG_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Experiment 0 config from {_CFG_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
