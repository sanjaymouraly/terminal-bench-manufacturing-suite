from __future__ import annotations

import tomllib
from pathlib import Path

from .models import TaskInfo
from .util import BenchError, project_root


def task_dirs(root: Path | None = None) -> list[Path]:
    suite = root or project_root()
    tasks_root = suite / "tasks"
    if not tasks_root.is_dir():
        raise BenchError(f"No tasks directory at {tasks_root}")
    return sorted(
        path for path in tasks_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


def load_task(path_or_slug: str | Path, root: Path | None = None) -> TaskInfo:
    suite = root or project_root()
    possible = Path(path_or_slug)
    task_path = possible if possible.is_dir() else suite / "tasks" / str(path_or_slug)
    task_path = task_path.resolve()
    task_toml = task_path / "task.toml"
    if not task_toml.is_file():
        raise BenchError(f"Task not found or task.toml missing: {path_or_slug}")
    try:
        raw = tomllib.loads(task_toml.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise BenchError(f"Invalid task.toml for {task_path.name}: {exc}") from exc
    task = raw.get("task", {})
    agent = raw.get("agent", {})
    verifier = raw.get("verifier", {})
    manifest_seed = None
    manifest = task_path / "environment" / "data" / "fixture-manifest.json"
    if manifest.is_file():
        import json

        try:
            manifest_seed = int(json.loads(manifest.read_text(encoding="utf-8")).get("seed"))
        except (TypeError, ValueError, json.JSONDecodeError):
            manifest_seed = None
    artifacts = raw.get("artifacts", [])
    normal_artifacts: list[str] = []
    for item in artifacts:
        if isinstance(item, str):
            normal_artifacts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("source"), str):
            normal_artifacts.append(item["source"])
    metadata = raw.get("metadata", {})
    return TaskInfo(
        slug=task_path.name,
        path=task_path,
        name=str(task.get("name", task_path.name)),
        version=str(task.get("version", "0.0.0")),
        description=str(task.get("description", "")),
        fixture_seed=manifest_seed,
        agent_timeout_sec=float(agent.get("timeout_sec", 0)),
        verifier_timeout_sec=float(verifier.get("timeout_sec", 0)),
        artifacts=tuple(normal_artifacts),
        tags=tuple(str(value) for value in metadata.get("tags", [])),
    )


def list_tasks(root: Path | None = None) -> list[TaskInfo]:
    return [load_task(path, root) for path in task_dirs(root)]
