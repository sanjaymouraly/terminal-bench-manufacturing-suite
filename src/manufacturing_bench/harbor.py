from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import RunResult
from .util import BenchError


@dataclass(frozen=True)
class ToolchainStatus:
    harbor_version: str | None
    docker_available: bool
    docker_detail: str


def harbor_version() -> str | None:
    executable = shutil.which("harbor")
    if not executable:
        return None
    completed = subprocess.run(
        [executable, "--version"], text=True, capture_output=True, check=False, timeout=15
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def docker_status() -> tuple[bool, str]:
    executable = shutil.which("docker")
    if not executable:
        return False, "Docker CLI was not found on PATH."
    try:
        completed = subprocess.run(
            [executable, "version", "--format", "{{.Server.Version}}"],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except OSError as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, (completed.stderr.strip() or "Docker daemon is unavailable.")
    return True, f"Docker server {completed.stdout.strip()}"


def toolchain_status() -> ToolchainStatus:
    available, detail = docker_status()
    return ToolchainStatus(harbor_version(), available, detail)


def build_harbor_command(
    task_path: Path,
    agent: str,
    model: str | None,
    attempts: int,
    *,
    agent_timeout_multiplier: float | None = None,
    agent_kwargs: tuple[str, ...] = (),
    jobs_dir: Path | None = None,
    job_name: str | None = None,
) -> list[str]:
    """Build a local Harbor command without launching it."""
    if attempts < 1:
        raise BenchError("--attempts must be at least 1.")
    if agent_timeout_multiplier is not None and agent_timeout_multiplier <= 0:
        raise BenchError("Agent timeout multiplier must be positive.")
    executable = shutil.which("harbor")
    if not executable:
        raise BenchError(
            "Harbor is not installed. Install with `uv tool install harbor` or `pip install harbor`."
        )
    command = [executable, "run", "-p", str(task_path), "-a", agent, "-k", str(attempts)]
    if model:
        command.extend(["-m", model])
    if jobs_dir is not None:
        command.extend(["--jobs-dir", str(jobs_dir)])
    if job_name:
        command.extend(["--job-name", job_name])
    if agent_timeout_multiplier is not None:
        command.extend(["--agent-timeout-multiplier", f"{agent_timeout_multiplier:.8g}"])
    for agent_kwarg in agent_kwargs:
        command.extend(["--agent-kwarg", agent_kwarg])
    return command


def runtime_limit_kwargs(
    agent: str,
    *,
    max_turns: int | None,
    max_thinking_tokens: int | None,
    max_budget_usd: float | None,
) -> tuple[str, ...]:
    """Translate supported Harbor agent budget controls into explicit kwargs.

    Harbor 0.24.0 exposes these controls for Claude Code and Terminus 2. Other
    agents must not receive speculative options that their schemas do not support.
    """
    if max_turns is not None and max_turns < 1:
        raise BenchError("--max-turns must be at least 1.")
    if max_thinking_tokens is not None and max_thinking_tokens < 1:
        raise BenchError("--max-thinking-tokens must be at least 1.")
    if max_budget_usd is not None and max_budget_usd < 0:
        raise BenchError("--max-budget-usd must be non-negative.")
    if max_turns is None and max_thinking_tokens is None and max_budget_usd is None:
        return ()

    if agent == "claude-code":
        kwargs: list[str] = []
        if max_turns is not None:
            kwargs.append(f"max_turns={max_turns}")
        if max_thinking_tokens is not None:
            kwargs.append(f"max_thinking_tokens={max_thinking_tokens}")
        if max_budget_usd is not None:
            kwargs.append(f"max_budget_usd={max_budget_usd:.6f}")
        return tuple(kwargs)
    if agent == "terminus-2":
        if max_budget_usd is not None:
            raise BenchError(
                "Harbor 0.24.0 Terminus 2 has no max_budget_usd agent option; use "
                "--max-estimated-usd for the documented preflight cap."
            )
        kwargs = []
        if max_turns is not None:
            kwargs.append(f"max_turns={max_turns}")
        if max_thinking_tokens is not None:
            kwargs.append(f"max_thinking_tokens={max_thinking_tokens}")
        return tuple(kwargs)
    raise BenchError(
        "Runtime turn/thinking/spend controls are supported by this wrapper only for "
        "claude-code or terminus-2. Use Harbor's documented agent schema for other agents."
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _primary_reward(verifier_result: Any) -> float:
    rewards = verifier_result.get("rewards", {}) if isinstance(verifier_result, dict) else {}
    if not isinstance(rewards, dict):
        return 0.0
    if "reward" in rewards:
        return _number(rewards["reward"]) or 0.0
    if len(rewards) == 1:
        return _number(next(iter(rewards.values()))) or 0.0
    return 0.0


def _usage_totals(
    payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None, float | None]:
    """Extract actual token/cost fields when a Harbor agent wrote them."""
    agent_result = payload.get("agent_result")
    contexts: list[dict[str, Any]] = []
    if isinstance(agent_result, dict):
        contexts.append(agent_result)
    else:
        steps = payload.get("step_results")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and isinstance(step.get("agent_result"), dict):
                    contexts.append(step["agent_result"])

    def total_int(field: str) -> int | None:
        values = [context.get(field) for context in contexts]
        parsed = [_number(value) for value in values]
        observed = [value for value in parsed if value is not None]
        return int(sum(observed)) if observed else None

    def total_float(field: str) -> float | None:
        values = [context.get(field) for context in contexts]
        parsed = [_number(value) for value in values]
        observed = [value for value in parsed if value is not None]
        return sum(observed) if observed else None

    return (
        total_int("n_input_tokens"),
        total_int("n_cache_tokens"),
        total_int("n_output_tokens"),
        total_float("cost_usd"),
    )


def _elapsed_seconds(started_at: Any, finished_at: Any) -> float:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return 0.0
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, round((finish - start).total_seconds(), 6))


def collect_harbor_results(
    job_dir: Path,
    *,
    root: Path,
    task: str,
    task_version: str,
    fixture_seed: int | None,
    fallback_agent: str,
    fallback_model: str | None,
    command: list[str],
    fallback_started_at: str,
) -> list[RunResult]:
    """Import observed Harbor trial results from a known job directory.

    Harbor 0.24.0 persists a `result.json` in every trial directory. The
    plural fallback accommodates older or externally produced job layouts while
    retaining a strict no-result outcome for callers to handle explicitly.
    """
    result_paths = sorted(
        {
            *job_dir.rglob("result.json"),
            *job_dir.rglob("results.json"),
        }
    )
    # Harbor 0.24.0 also writes a job-level result.json. Only trial directories
    # contain verifier outcomes; importing the job summary would create a fake
    # infrastructure-error run alongside every real trial.
    result_paths = [path for path in result_paths if path.parent != job_dir]
    if not result_paths and (job_dir / "result.json").is_file():
        result_paths = [job_dir / "result.json"]
    imported: list[RunResult] = []
    for index, result_path in enumerate(result_paths, start=1):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        verifier_result = payload.get("verifier_result")
        exception = payload.get("exception_info")
        score = _primary_reward(verifier_result)
        passed = score == 1.0
        diagnostics: list[str] = []
        status: str
        failure_category: str | None
        if isinstance(exception, dict):
            exception_type = str(exception.get("exception_type", "HarborTrialError"))
            exception_message = str(exception.get("exception_message", ""))
            diagnostics.append(f"{exception_type}: {exception_message}".rstrip())
            status = "agent_error"
            failure_category = "harbor_exception"
        elif isinstance(verifier_result, dict):
            status = "passed" if passed else "incorrect_output"
            failure_category = None if passed else "verification"
        else:
            status = "infrastructure_error"
            failure_category = "missing_verifier_result"
            diagnostics.append("Harbor result has no verifier result.")

        agent_info = payload.get("agent_info")
        agent: str = fallback_agent
        model = fallback_model
        if isinstance(agent_info, dict):
            agent_name = agent_info.get("name")
            if isinstance(agent_name, str) and agent_name:
                agent = agent_name
            model_info = agent_info.get("model_info")
            if isinstance(model_info, dict) and model_info.get("name"):
                model_name = str(model_info["name"])
                provider = model_info.get("provider")
                model = f"{provider}/{model_name}" if provider else model_name
        started_at = payload.get("started_at")
        started = started_at if isinstance(started_at, str) else fallback_started_at
        input_tokens, cache_tokens, output_tokens, cost_usd = _usage_totals(payload)
        try:
            artifact_dir = str(result_path.parent.relative_to(root))
        except ValueError:
            artifact_dir = str(result_path.parent)
        imported.append(
            RunResult(
                run_id=str(payload.get("id") or f"{job_dir.name}-{index}"),
                task=task,
                task_version=task_version,
                fixture_seed=fixture_seed,
                agent=agent,
                model=model,
                score=score,
                passed=passed,
                status=status,
                failure_category=failure_category,
                started_at=started,
                elapsed_seconds=_elapsed_seconds(started_at, payload.get("finished_at")),
                artifact_dir=artifact_dir,
                command=command,
                input_tokens=input_tokens,
                cache_tokens=cache_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                diagnostics=diagnostics,
            )
        )
    return imported


_TRANSIENT_INFRASTRUCTURE_MARKERS = (
    "connection reset",
    "connection refused",
    "docker daemon",
    "temporarily unavailable",
    "tls handshake timeout",
    "i/o timeout",
    "network is unreachable",
)


def execute_harbor(
    command: list[str],
    root: Path,
    *,
    max_infrastructure_retries: int = 0,
    retry_delay_seconds: float = 2.0,
) -> int:
    """Run Harbor with bounded retries only for recognizable infrastructure failures.

    Agent/verifier results are never retried here: Harbor normally completes those
    jobs with a result, and retrying them would distort evaluation statistics.
    """
    available, detail = docker_status()
    if not available:
        raise BenchError(f"Cannot execute Harbor locally: {detail}")
    for attempt in range(max_infrastructure_retries + 1):
        completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        if completed.returncode == 0:
            return 0
        diagnostic = (completed.stdout + "\n" + completed.stderr).lower()
        transient = any(marker in diagnostic for marker in _TRANSIENT_INFRASTRUCTURE_MARKERS)
        if not transient or attempt >= max_infrastructure_retries:
            return completed.returncode
        time.sleep(max(0.0, retry_delay_seconds))
    return 1
