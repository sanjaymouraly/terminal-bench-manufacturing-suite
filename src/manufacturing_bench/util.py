from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class BenchError(RuntimeError):
    """A user-facing, actionable benchmark-management error."""


def project_root(start: Path | None = None) -> Path:
    """Find the checked-out suite root without relying on the current directory."""
    configured = os.environ.get("MFG_BENCH_ROOT")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if (candidate / "pyproject.toml").is_file() and (candidate / "tasks").is_dir():
            return candidate
        raise BenchError("MFG_BENCH_ROOT does not point to a suite checkout with tasks/.")
    candidates: list[Path] = []
    if start:
        candidates.append(start.resolve())
    candidates.extend([Path.cwd().resolve(), Path(__file__).resolve()])
    for candidate in candidates:
        for parent in (candidate, *candidate.parents):
            if (parent / "pyproject.toml").is_file() and (parent / "tasks").is_dir():
                return parent
    raise BenchError(
        "Could not locate the suite root. Run from the repository or set MFG_BENCH_ROOT."
    )


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchError(f"Required JSON file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchError(f"Invalid JSON in {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(path: Path, *, exclude: Iterable[str] = ()) -> str:
    """Hash relative paths and bytes deterministically; intended for provenance, not security."""
    ignored = tuple(exclude)
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix()
        if any(item.match(pattern) or relative == pattern for pattern in ignored):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def copy_tree_readonly(source: Path, destination: Path) -> None:
    """Copy data into a local simulation workspace and make raw files read-only."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    for item in destination.rglob("*"):
        if item.is_file():
            item.chmod(0o444)
        elif item.is_dir():
            item.chmod(0o555)
    destination.chmod(0o555)


def safe_under(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    value = candidate.resolve()
    try:
        value.relative_to(root_resolved)
    except ValueError as exc:
        raise BenchError(f"Refusing to operate outside suite root: {value}") from exc
    return value


def remove_tree_safe(root: Path, candidate: Path) -> None:
    resolved = safe_under(root, candidate)
    if resolved == root.resolve():
        raise BenchError("Refusing to remove the suite root.")
    if resolved.exists():
        shutil.rmtree(resolved)


def slugify(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or "run"


def temporary_directory(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
