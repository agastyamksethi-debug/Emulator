"""
Parts package — simulated component library.

Directory names use hyphens (e.g. 'esp32-wroom-32') which are not valid
Python identifiers. Use load_part() to import a part by directory name.

Usage:
    import parts
    parts.load_part("esp32-wroom-32")   # registers the part as a side effect

    from core.runner import SimRunner
    runner = SimRunner()
    runner.load("board.kicad_sch")
"""

from __future__ import annotations
import importlib.util
import os

_PARTS_DIR = os.path.dirname(__file__)


def load_part(part_name: str):
    """
    Import a part's model.py by directory name.

    Handles hyphenated names (e.g. 'esp32-wroom-32').
    register_part() at the bottom of every model.py runs as a side effect.
    Returns the loaded module.
    """
    model_path = os.path.join(_PARTS_DIR, part_name, "model.py")
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"No model.py found for part '{part_name}' "
            f"(looked in {model_path})"
        )
    module_name = f"parts.{part_name.replace('-', '_')}.model"
    spec   = importlib.util.spec_from_file_location(module_name, model_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
