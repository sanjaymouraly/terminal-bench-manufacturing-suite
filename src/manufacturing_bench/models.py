from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskInfo:
    slug: str
    path: Path
    name: str
    version: str
    description: str
    fixture_seed: int | None
    agent_timeout_sec: float
    verifier_timeout_sec: float
    artifacts: tuple[str, ...]
    tags: tuple[str, ...] = ()


@dataclass
class ValidationIssue:
    level: str  # error, warning, info
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class VerificationResult:
    reward: float
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @classmethod
    def failed(cls, message: str) -> VerificationResult:
        return cls(reward=0.0, passed=False, diagnostics=[message])


@dataclass
class RunResult:
    run_id: str
    task: str
    task_version: str
    fixture_seed: int | None
    agent: str
    model: str | None
    score: float
    passed: bool
    status: str
    failure_category: str | None
    started_at: str
    elapsed_seconds: float
    artifact_dir: str
    command: list[str]
    input_tokens: int | None = None
    cache_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
