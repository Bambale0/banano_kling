"""Expose the repository's real ``bot`` package to directly executed scripts.

When Python runs ``python scripts/example.py``, ``scripts/`` becomes the first
entry in ``sys.path`` and the repository root is not importable automatically.
This lightweight package shim points submodule lookups such as ``bot.env`` and
``bot.db`` at the real top-level ``bot/`` directory.

It is only selected for direct script execution. Normal application and test
imports continue to use ``bot/__init__.py`` from the repository root.
"""

from __future__ import annotations

from pathlib import Path

_REAL_BOT_DIR = Path(__file__).resolve().parents[1] / "bot"
if not _REAL_BOT_DIR.is_dir():
    raise ImportError(f"Real bot package directory not found: {_REAL_BOT_DIR}")

# Defining __path__ makes this module package-like, so ``from bot.env import …``
# resolves modules from the actual repository package directory.
__path__ = [str(_REAL_BOT_DIR)]
__version__ = "1.0.0"
