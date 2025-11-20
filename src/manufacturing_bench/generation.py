from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .tasks import task_dirs
from .util import BenchError


def generate_fixtures(
    root: Path,
    *,
    task: str | None,
    profile: str,
    target: Path | None,
    write_canonical: bool = False,
) -> None:
    """Delegate deterministic fixture emission to the checked-in generator.

    Canonical evaluation fixtures are intentionally updated only with an explicit
    flag because those bytes are part of task provenance and verifier reproducibility.
    """
    generator = root / "scripts" / "generate_fixtures.py"
    if not generator.is_file():
        raise BenchError("Fixture generator is missing: scripts/generate_fixtures.py")
    selected = [task] if task else [item.name for item in task_dirs(root)]
    for slug in selected:
        command = [sys.executable, str(generator), "--task", slug, "--profile", profile]
        if target:
            command.extend(["--target", str(target / slug)])
        if write_canonical:
            command.append("--write-canonical")
        completed = subprocess.run(command, cwd=root, text=True, check=False)
        if completed.returncode != 0:
            raise BenchError(f"Fixture generation failed for {slug} (exit {completed.returncode}).")
