"""Characterization test: no bare `except:` clauses.

P2-02: bare `except:` catches KeyboardInterrupt, SystemExit, and
GeneratorExit — only `except Exception:` should be used.
"""

import ast
import os
from pathlib import Path


def _find_py_files(root_dir: str) -> list[str]:
    """Recursively find all .py files (no venv, no pycache)."""
    py_files = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip virtual envs and cache
        dirnames[:] = [
            d for d in dirnames
            if d not in ("venv", ".venv", "__pycache__", ".git", "node_modules")
        ]
        for f in filenames:
            if f.endswith(".py"):
                py_files.append(os.path.join(dirpath, f))
    return py_files


def test_no_bare_excepts():
    """No file should contain a bare `except:` clause."""
    root = Path(__file__).resolve().parent.parent / "bot"
    bad_files = []

    for py_file in _find_py_files(str(root)):
        with open(py_file) as f:
            try:
                tree = ast.parse(f.read(), filename=py_file)
            except SyntaxError:
                continue  # skip files with syntax errors (e.g. ipynb fragments)

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:  # bare except
                    bad_files.append(
                        f"{py_file}:{getattr(node, 'lineno', '?')} — bare except handler"
                    )

    if bad_files:
        msg = "\n".join(bad_files)
        raise AssertionError(f"Found {len(bad_files)} bare except(s):\n{msg}")
