from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from manufacturing_bench.tasks import list_tasks
from manufacturing_bench.util import project_root
from scripts.generate_fixtures import make_files


def test_eval_generation_is_deterministic_and_matches_manifest() -> None:
    root = project_root()
    for task in list_tasks(root):
        one = make_files(task.slug, "eval")
        two = make_files(task.slug, "eval")
        assert one == two
        manifest = json.loads(one["fixture-manifest.json"])
        assert manifest["seed"] == task.fixture_seed
        checked_in = task.path / "environment" / "data"
        private_copy = task.path / "tests" / "private"
        for name, content in one.items():
            assert (checked_in / name).read_text(encoding="utf-8") == content
            assert (private_copy / name).read_text(encoding="utf-8") == content


def test_dev_and_stress_profiles_are_distinct_and_documented() -> None:
    for task in list_tasks(project_root()):
        dev = make_files(task.slug, "dev")
        stress = make_files(task.slug, "stress")
        assert json.loads(dev["fixture-manifest.json"])["profile"] == "dev"
        assert json.loads(stress["fixture-manifest.json"])["profile"] == "stress"
        assert "STRESS_PROFILE.md" in stress


def test_development_profiles_remain_oracle_solvable(tmp_path: Path) -> None:
    """Development fixtures are reduced but preserve enough referential evidence to run."""
    for task in list_tasks(project_root()):
        data = tmp_path / task.slug / "data"
        data.mkdir(parents=True)
        for name, content in make_files(task.slug, "dev").items():
            (data / name).write_text(content, encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(task.path / "solution" / "solve.py"),
                "--data",
                str(data),
                "--output",
                str(data.parent / "output"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, (task.slug, completed.stderr)
