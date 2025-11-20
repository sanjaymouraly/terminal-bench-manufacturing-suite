from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from .database import RunStore
from .harbor import harbor_version
from .models import RunResult
from .tasks import load_task
from .util import BenchError, copy_tree_readonly, utc_now, write_json

LocalAgent = Literal["oracle", "nop", "mutation"]


def _write_log(path: Path, title: str, completed: subprocess.CompletedProcess[str]) -> None:
    path.write_text(
        f"# {title}\n# returncode: {completed.returncode}\n\n"
        f"## stdout\n{completed.stdout}\n\n## stderr\n{completed.stderr}\n",
        encoding="utf-8",
    )


def _mutate_artifact(path: Path) -> None:
    """Perturb one meaningful value while keeping the artifact schema valid.

    The mutation is used solely to regression-test that the verifier rejects a
    plausible-looking but financially/operationally incorrect submission, rather
    than only rejecting an empty or unparsable file.
    """
    if not path.exists():
        return
    if path.suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.write_text('{"__deliberate_mutation__": true}\n', encoding="utf-8")
            return

        def perturb(value: Any) -> bool:
            if isinstance(value, dict):
                for key in value:
                    if isinstance(key, str) and (
                        key.endswith("_inr") or key.endswith("_qty") or key.endswith("_base")
                    ):
                        if isinstance(value[key], str):
                            try:
                                value[key] = format(Decimal(value[key]) + Decimal("1.00"), "f")
                                return True
                            except (ArithmeticError, ValueError):
                                continue
                        elif isinstance(value[key], (int, float)):
                            value[key] = value[key] + 1
                            return True
                return any(perturb(item) for item in value.values())
            if isinstance(value, list):
                return any(perturb(item) for item in value)
            return False

        if not perturb(payload):
            path.write_text('{"__deliberate_mutation__": true}\n', encoding="utf-8")
            return
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    if path.suffix == ".jsonl":
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            path.write_text("__deliberate_mutation__\n", encoding="utf-8")
            return
        first = json.loads(lines[0])
        for key in ("qty", "qty_base", "consumed_qty"):
            if key in first:
                first[key] = format(Decimal(str(first[key])) + Decimal("1"), "f")
                break
        else:
            first["__deliberate_mutation__"] = True
        lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    # CSV: change the first monetary/quantity-looking cell, preserving the header.
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows or not fields:
        path.write_text("__deliberate_mutation__\n", encoding="utf-8")
        return
    changed = False
    for field in fields:
        if field.endswith("_inr") or field.endswith("_qty") or field.endswith("_base"):
            value = rows[0][field]
            try:
                rows[0][field] = format(Decimal(value) + Decimal("1.00"), "f")
                changed = True
                break
            except (ArithmeticError, ValueError):
                continue
    if not changed:
        rows[0][fields[-1]] = "__deliberate_mutation__"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _run_command(
    command: list[str], *, timeout: float, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=max(1, int(timeout)),
        check=False,
    )


def run_local(
    task_name: str,
    *,
    agent: LocalAgent = "oracle",
    root: Path,
    model: str | None = None,
    runs_dir: Path | None = None,
    keep_workspace: bool = True,
    record_run: bool = True,
) -> RunResult:
    """Run the offline Oracle/NOP/mutation harness without requiring Docker.

    This is intentionally a development harness, not a substitute for Harbor's container
    isolation. It mirrors the declared artifact boundary: only /app/output is passed to
    the separate Python verifier.
    """
    if agent not in {"oracle", "nop", "mutation"}:
        raise BenchError(f"Unsupported local agent {agent!r}; choose oracle, nop, or mutation.")
    task = load_task(task_name, root)
    base_runs = runs_dir or root / "runs"
    run_id = f"{task.slug}-{agent}-{uuid.uuid4().hex[:12]}"
    run_dir = base_runs / run_id
    workspace = run_dir / "workspace"
    output_dir = workspace / "output"
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    start = time.monotonic()
    diagnostics: list[str] = []
    command: list[str] = []
    score = 0.0
    passed = False
    status = "infrastructure_error"
    failure_category: str | None = "infrastructure"

    try:
        copy_tree_readonly(task.path / "environment" / "data", workspace / "data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir.chmod(0o755)
        runtime_env = dict(os.environ)
        runtime_env.update({"PYTHONUTF8": "1", "MFG_LOCAL_RUN": "1"})
        if agent in {"oracle", "mutation"}:
            command = [
                sys.executable,
                str(task.path / "solution" / "solve.py"),
                "--data",
                str(workspace / "data"),
                "--output",
                str(output_dir),
            ]
            try:
                completed = _run_command(
                    command,
                    timeout=task.agent_timeout_sec,
                    cwd=workspace,
                    env=runtime_env,
                )
            except subprocess.TimeoutExpired:
                diagnostics.append("Oracle timed out in the local development harness.")
                status = "agent_timeout"
                failure_category = "timeout"
                completed = None
            if completed is not None:
                _write_log(run_dir / "agent.log", "local oracle", completed)
                if completed.returncode != 0:
                    diagnostics.append(f"Oracle exited {completed.returncode}; see agent.log.")
                    status = "agent_error"
                    failure_category = "oracle_error"
        else:
            command = ["nop"]
            (run_dir / "agent.log").write_text(
                "NOP baseline intentionally wrote no artifact.\n", encoding="utf-8"
            )

        if agent == "mutation" and all(
            (output_dir / Path(item).name).exists() for item in task.artifacts
        ):
            # Artifacts are absolute /app/output paths; only mutate the first declared transfer.
            _mutate_artifact(output_dir / Path(task.artifacts[0]).name)
            diagnostics.append(
                "Deliberately mutated the first transferred artifact after Oracle completion."
            )

        verifier_result_path = run_dir / "verifier-result.json"
        verify_command = [
            sys.executable,
            str(task.path / "tests" / "verify.py"),
            "--artifact-root",
            str(workspace),
            "--private-root",
            str(task.path / "tests" / "private"),
            "--result",
            str(verifier_result_path),
        ]
        try:
            verified = _run_command(
                verify_command,
                timeout=task.verifier_timeout_sec,
                cwd=run_dir,
                env=runtime_env,
            )
        except subprocess.TimeoutExpired:
            diagnostics.append("Verifier timed out in the local development harness.")
            status = "verifier_timeout"
            failure_category = "verifier_timeout"
            verified = None
        if verified is not None:
            _write_log(run_dir / "verifier.log", "local separate verifier", verified)
            if verifier_result_path.is_file():
                try:
                    payload = json.loads(verifier_result_path.read_text(encoding="utf-8"))
                    score = float(payload.get("reward", 0.0))
                    passed = score == 1.0
                    diagnostics.extend(str(item) for item in payload.get("diagnostics", []))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    diagnostics.append(f"Could not parse verifier result: {exc}")
            if passed:
                status = "passed"
                failure_category = None
            elif verified.returncode == 0:
                status = "incorrect_output"
                failure_category = "verification"
            else:
                status = "incorrect_output"
                failure_category = "verification"
                diagnostics.append(
                    f"Verifier rejected artifacts (exit {verified.returncode}); see verifier.log."
                )
    except Exception as exc:  # retain run diagnostics instead of hiding engineering failures
        diagnostics.append(f"Local harness exception: {exc}")
        diagnostics.append(traceback.format_exc(limit=5))
        status = "infrastructure_error"
        failure_category = "harness"

    elapsed = round(time.monotonic() - start, 6)
    try:
        artifact_location = str(run_dir.relative_to(root))
    except ValueError:
        # Test callers may intentionally retain artifacts in an external temporary directory.
        artifact_location = str(run_dir)
    result = RunResult(
        run_id=run_id,
        task=task.slug,
        task_version=task.version,
        fixture_seed=task.fixture_seed,
        agent=agent,
        model=model,
        score=score,
        passed=passed,
        status=status,
        failure_category=failure_category,
        started_at=started_at,
        elapsed_seconds=elapsed,
        artifact_dir=artifact_location,
        command=command,
        diagnostics=diagnostics,
    )
    write_json(run_dir / "run.json", result.to_dict())
    if record_run:
        RunStore(root / ".mfgbench" / "runs.sqlite3").record(result, harbor_version())
    if not keep_workspace:
        shutil.rmtree(workspace, ignore_errors=True)
    return result
