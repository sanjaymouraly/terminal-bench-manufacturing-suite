from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from manufacturing_bench.tasks import list_tasks
from manufacturing_bench.util import project_root


@pytest.mark.skipif(
    shutil.which("sh") is None,
    reason="test.sh requires a POSIX shell; the Harbor/Docker CI job exercises it on Linux.",
)
def test_harbor_reward_entrypoints_accept_oracle_and_reject_nop(tmp_path: Path) -> None:
    """Exercise each exact test.sh reward contract without requiring Docker."""
    root = project_root()
    for task in list_tasks(root):
        sandbox = tmp_path / task.slug
        artifact_root = sandbox / "app"
        output = artifact_root / "output"
        output.mkdir(parents=True)
        subprocess.run(
            [
                sys.executable,
                str(task.path / "solution" / "solve.py"),
                "--data",
                str(task.path / "environment" / "data"),
                "--output",
                str(output),
            ],
            check=True,
            text=True,
        )
        logs = sandbox / "logs" / "verifier"
        environment = {
            **os.environ,
            "TESTS_ROOT": str(task.path / "tests"),
            "ARTIFACT_ROOT": str(artifact_root),
            "VERIFIER_LOG_ROOT": str(logs),
        }
        completed = subprocess.run(
            ["sh", str(task.path / "tests" / "test.sh")],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert (logs / "reward.txt").read_text().strip() == "1"

        shutil.rmtree(output)
        output.mkdir()
        completed = subprocess.run(
            ["sh", str(task.path / "tests" / "test.sh")],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert (logs / "reward.txt").read_text().strip() == "0"
