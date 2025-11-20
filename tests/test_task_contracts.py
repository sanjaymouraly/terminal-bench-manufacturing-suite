from __future__ import annotations

import json
from pathlib import Path

from manufacturing_bench.local_runner import run_local
from manufacturing_bench.tasks import list_tasks
from manufacturing_bench.util import project_root
from manufacturing_bench.validator import validate_task


def test_exactly_five_task_packages() -> None:
    root = project_root()
    assert [task.slug for task in list_tasks(root)] == [
        "bom-consistency-audit",
        "inventory-corruption-recovery",
        "manufacturing-cost-variance",
        "production-data-repair",
        "supplier-reconciliation",
    ]


def test_task_static_contracts_have_no_errors() -> None:
    root = project_root()
    for task in list_tasks(root):
        errors = [issue for issue in validate_task(task.path) if issue.level == "error"]
        assert not errors, f"{task.slug}: {errors}"


def test_bom_fixture_exercises_multi_node_cycle_detection(tmp_path: Path) -> None:
    root = project_root()
    result = run_local(
        "bom-consistency-audit",
        agent="oracle",
        root=root,
        runs_dir=tmp_path / "runs",
        record_run=False,
    )
    assert result.score == 1.0
    report = json.loads(
        (Path(result.artifact_dir) / "workspace" / "output" / "validation_report.json").read_text(
            encoding="utf-8"
        )
    )
    lengths = [len(item["cycle_path"]) for item in report["cycle_findings"]]
    assert any(length >= 3 for length in lengths), lengths
    assert all(item["status"] == "DRAFT_NOT_SELECTABLE" for item in report["cycle_findings"])


def test_oracle_nop_and_mutation_contracts(tmp_path: Path) -> None:
    root = project_root()
    for task in list_tasks(root):
        oracle = run_local(
            task.slug, agent="oracle", root=root, runs_dir=tmp_path / "runs", record_run=False
        )
        nop = run_local(
            task.slug, agent="nop", root=root, runs_dir=tmp_path / "runs", record_run=False
        )
        mutation = run_local(
            task.slug, agent="mutation", root=root, runs_dir=tmp_path / "runs", record_run=False
        )
        assert oracle.score == 1.0, (task.slug, oracle.diagnostics)
        assert nop.score == 0.0, (task.slug, nop.diagnostics)
        assert mutation.score == 0.0, (task.slug, mutation.diagnostics)
