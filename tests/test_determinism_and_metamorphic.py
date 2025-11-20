from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from manufacturing_bench.local_runner import run_local
from manufacturing_bench.tasks import list_tasks
from manufacturing_bench.util import project_root, sha256_tree


def test_oracle_artifacts_are_repeatably_identical(tmp_path: Path) -> None:
    """Regression gate: deterministic raw inputs must produce byte-identical output artifacts."""
    root = project_root()
    for task in list_tasks(root):
        first = run_local(
            task.slug,
            agent="oracle",
            root=root,
            runs_dir=tmp_path / "runs",
            record_run=False,
        )
        second = run_local(
            task.slug,
            agent="oracle",
            root=root,
            runs_dir=tmp_path / "runs",
            record_run=False,
        )
        first_output = Path(first.artifact_dir) / "workspace" / "output"
        second_output = Path(second.artifact_dir) / "workspace" / "output"
        assert first.score == second.score == 1.0
        assert sha256_tree(first_output) == sha256_tree(second_output)


@settings(max_examples=10, deadline=None)
@given(st.data())
def test_inventory_replay_is_invariant_to_source_log_permutation(data) -> None:
    """Property/metamorphic test: replay result depends on event evidence, not JSONL order."""
    root = project_root()
    task = root / "tasks" / "inventory-corruption-recovery"
    source = task / "environment" / "data"
    events = (source / "stock_events.jsonl").read_text(encoding="utf-8").splitlines()
    permutation = data.draw(st.permutations(range(len(events))))
    with tempfile.TemporaryDirectory(prefix="mfg-permutation-") as temporary:
        work = Path(temporary)
        copied = work / "data"
        shutil.copytree(source, copied)
        (copied / "stock_events.jsonl").write_text(
            "\n".join(events[index] for index in permutation) + "\n", encoding="utf-8"
        )
        output = work / "output"
        completed = subprocess.run(
            [
                sys.executable,
                str(task / "solution" / "solve.py"),
                "--data",
                str(copied),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        baseline = work / "baseline"
        baseline.mkdir()
        baseline_completed = subprocess.run(
            [
                sys.executable,
                str(task / "solution" / "solve.py"),
                "--data",
                str(source),
                "--output",
                str(baseline),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert baseline_completed.returncode == 0, baseline_completed.stderr
        assert sha256_tree(output) == sha256_tree(baseline)
        # The task's duplicate/conflict rules must still be represented in the audit.
        audit = json.loads((output / "recovery_audit.json").read_text(encoding="utf-8"))
        assert audit["dropped_exact_duplicate_ids"] == ["EV-001", "EV-101"]
        assert audit["quarantined_conflict_ids"] == ["EV-013", "EV-105"]
