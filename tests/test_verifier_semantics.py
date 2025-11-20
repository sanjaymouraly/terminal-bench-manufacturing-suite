from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from manufacturing_bench.local_runner import run_local
from manufacturing_bench.util import project_root


def _run_verifier(task_path: Path, workspace: Path, result: Path) -> float:
    completed = subprocess.run(
        [
            sys.executable,
            str(task_path / "tests" / "verify.py"),
            "--artifact-root",
            str(workspace),
            "--private-root",
            str(task_path / "tests" / "private"),
            "--result",
            str(result),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode in {0, 1}, completed.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    return float(payload["reward"])


def _oracle_workspace(task: str, tmp_path: Path) -> tuple[Path, Path]:
    root = project_root()
    result = run_local(
        task,
        agent="oracle",
        root=root,
        runs_dir=tmp_path / "runs",
        record_run=False,
    )
    assert result.score == 1.0, result.diagnostics
    workspace = Path(result.artifact_dir) / "workspace"
    return root / "tasks" / task, workspace


def _rewrite_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_free_text_fields_are_not_hidden_expected_answers(tmp_path: Path) -> None:
    """A correct calculation must pass even when audit prose is phrased differently."""
    task_path, workspace = _oracle_workspace("supplier-reconciliation", tmp_path)
    disputes = workspace / "output" / "disputes.csv"
    with disputes.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        row["detail"] = "Controller-reviewed narrative with different wording."
    with disputes.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _rewrite_json(
        workspace / "output" / "audit.json",
        lambda payload: payload.update(
            {"policy": "Free-text policy summary supplied by the agent."}
        ),
    )
    assert _run_verifier(task_path, workspace, tmp_path / "supplier-result.json") == 1.0

    task_path, workspace = _oracle_workspace("manufacturing-cost-variance", tmp_path)
    _rewrite_json(
        workspace / "output" / "variance_report.json",
        lambda payload: payload.update({"rounding_policy": "Agent-written rounding narrative."}),
    )
    _rewrite_json(
        workspace / "output" / "investigation_findings.json",
        lambda payload: payload.update({"accounting_policies": ["Agent-written policy note."]}),
    )
    assert _run_verifier(task_path, workspace, tmp_path / "cost-result.json") == 1.0

    task_path, workspace = _oracle_workspace("bom-consistency-audit", tmp_path)
    repair_log = workspace / "output" / "repair_log.csv"
    with repair_log.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        row["evidence"] = "Different but non-empty reviewer evidence text."
    with repair_log.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    assert _run_verifier(task_path, workspace, tmp_path / "bom-result.json") == 1.0


def test_schema_valid_but_incorrect_values_are_rejected(tmp_path: Path) -> None:
    """A plausible, parseable report with one wrong financial value must fail."""
    checks = {
        "supplier-reconciliation": (
            "reconciliation.json",
            lambda payload: payload.update({"net_payable_inr": "0.00"}),
        ),
        "manufacturing-cost-variance": (
            "variance_report.json",
            lambda payload: payload.update({"total_variance_inr": "0.00"}),
        ),
        "bom-consistency-audit": (
            "validation_report.json",
            lambda payload: payload.update({"blocked_orders": []}),
        ),
        "production-data-repair": (
            "repair_audit.json",
            lambda payload: payload.update({"dropped_duplicate_ids": []}),
        ),
    }
    for task, (filename, mutate) in checks.items():
        task_path, workspace = _oracle_workspace(task, tmp_path)
        _rewrite_json(workspace / "output" / filename, mutate)
        reward = _run_verifier(task_path, workspace, tmp_path / f"{task}-bad.json")
        assert reward == 0.0, f"{task} accepted a schema-valid but incorrect value"
