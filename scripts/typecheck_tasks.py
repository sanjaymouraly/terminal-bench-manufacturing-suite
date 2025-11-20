#!/usr/bin/env python3
"""Run strict mypy checks for standalone task programs without module-name collisions.

Task packages deliberately use conventional standalone filenames such as
``solution/solve.py`` and ``tests/reference.py``. Passing every task path to one
mypy process would therefore make unrelated files appear to be duplicate modules.
This runner checks each independently, using the repository's shared strict mypy
configuration, and returns a nonzero status if any target fails.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_TARGET_PATTERNS = (
    "tasks/*/solution/solve.py",
    "tasks/*/tests/reference.py",
    "tasks/*/tests/verify.py",
)


def targets(root: Path) -> list[Path]:
    """Return deterministic standalone task-program paths required for type checks."""
    paths = [path for pattern in _TARGET_PATTERNS for path in root.glob(pattern)]
    return sorted(paths)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = targets(root)
    if not paths:
        print("No task Python programs found for type checking.", file=sys.stderr)
        return 2

    failures: list[Path] = []
    for path in paths:
        display = path.relative_to(root)
        print(f"== mypy {display} ==", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "mypy", str(display)],
            cwd=root,
            check=False,
        )
        if result.returncode:
            failures.append(display)

    if failures:
        print("Task type checks failed:", file=sys.stderr)
        for path in failures:
            print(f"- {path}", file=sys.stderr)
        return 1

    print(f"Strict mypy passed for {len(paths)} standalone task programs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
