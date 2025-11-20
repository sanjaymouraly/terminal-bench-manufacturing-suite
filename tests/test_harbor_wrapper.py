from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from manufacturing_bench import cli, harbor
from manufacturing_bench.util import BenchError, project_root


def test_harbor_wrapper_retries_only_recognized_transient_infrastructure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harbor, "docker_status", lambda: (True, "Docker server test"))
    calls: list[list[str]] = []
    results = [
        subprocess.CompletedProcess(["harbor"], 1, stdout="", stderr="connection reset by peer"),
        subprocess.CompletedProcess(["harbor"], 0, stdout="ok\n", stderr=""),
    ]

    def fake_run(command, **_kwargs):
        calls.append(command)
        return results.pop(0)

    monkeypatch.setattr(harbor.subprocess, "run", fake_run)
    monkeypatch.setattr(harbor.time, "sleep", lambda _seconds: None)
    assert harbor.execute_harbor(["harbor", "run"], tmp_path, max_infrastructure_retries=1) == 0
    assert len(calls) == 2


def test_harbor_wrapper_does_not_retry_nontransient_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(harbor, "docker_status", lambda: (True, "Docker server test"))
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="agent error", stderr="")

    monkeypatch.setattr(harbor.subprocess, "run", fake_run)
    assert harbor.execute_harbor(["harbor", "run"], tmp_path, max_infrastructure_retries=3) == 1
    assert len(calls) == 1


def test_harbor_command_and_runtime_limits_are_explicit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        harbor.shutil, "which", lambda name: "/usr/bin/harbor" if name == "harbor" else None
    )
    agent_kwargs = harbor.runtime_limit_kwargs(
        "claude-code", max_turns=12, max_thinking_tokens=2048, max_budget_usd=3.5
    )
    assert agent_kwargs == (
        "max_turns=12",
        "max_thinking_tokens=2048",
        "max_budget_usd=3.500000",
    )
    command = harbor.build_harbor_command(
        tmp_path,
        "claude-code",
        "anthropic/example",
        2,
        agent_timeout_multiplier=0.5,
        agent_kwargs=agent_kwargs,
    )
    assert command == [
        "/usr/bin/harbor",
        "run",
        "-p",
        str(tmp_path),
        "-a",
        "claude-code",
        "-k",
        "2",
        "-m",
        "anthropic/example",
        "--agent-timeout-multiplier",
        "0.5",
        "--agent-kwarg",
        "max_turns=12",
        "--agent-kwarg",
        "max_thinking_tokens=2048",
        "--agent-kwarg",
        "max_budget_usd=3.500000",
    ]
    with pytest.raises(BenchError, match="only for claude-code or terminus-2"):
        harbor.runtime_limit_kwargs(
            "codex", max_turns=2, max_thinking_tokens=None, max_budget_usd=None
        )
    with pytest.raises(BenchError, match="no max_budget_usd"):
        harbor.runtime_limit_kwargs(
            "terminus-2", max_turns=None, max_thinking_tokens=None, max_budget_usd=1
        )


def test_harbor_result_import_ignores_job_summary_and_reads_trial(tmp_path: Path) -> None:
    job = tmp_path / "job"
    trial = job / "task__abc"
    trial.mkdir(parents=True)
    (job / "result.json").write_text(
        json.dumps({"n_total_trials": 1, "stats": {"n_completed_trials": 1}}),
        encoding="utf-8",
    )
    (trial / "result.json").write_text(
        json.dumps(
            {
                "id": "trial-1",
                "task_name": "suite/task",
                "started_at": "2026-10-19T00:00:00Z",
                "finished_at": "2026-10-19T00:00:10Z",
                "agent_info": {"name": "oracle", "model_info": None},
                "verifier_result": {"rewards": {"reward": 1.0}},
                "exception_info": None,
                "agent_result": {"n_input_tokens": None},
            }
        ),
        encoding="utf-8",
    )
    imported = harbor.collect_harbor_results(
        job,
        root=tmp_path,
        task="task",
        task_version="1.0.0",
        fixture_seed=1,
        fallback_agent="unknown",
        fallback_model=None,
        command=["harbor", "run"],
        fallback_started_at="2026-10-19T00:00:00Z",
    )
    assert len(imported) == 1
    assert imported[0].score == 1.0
    assert imported[0].agent == "oracle"


def test_cli_paid_trial_budget_is_dry_run_safe_and_confirmation_gated(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    config = tmp_path / "providers.toml"
    config.write_text(
        """[providers.demo]
kind = "openai-compatible"
base_url = "https://example.invalid/v1"
api_key_env = ""
paid = true
input_usd_per_million = 2.0
output_usd_per_million = 6.0
pricing_as_of = "2026-10-18"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        harbor.shutil, "which", lambda name: "/usr/bin/harbor" if name == "harbor" else None
    )
    common = [
        "--root",
        str(project_root()),
        "harbor-run",
        "supplier-reconciliation",
        "--agent",
        "claude-code",
        "--model",
        "demo/model",
        "--provider",
        "demo",
        "--provider-config",
        str(config),
        "--attempts",
        "2",
        "--max-turns",
        "12",
        "--planned-input-tokens",
        "1000000",
        "--planned-output-tokens",
        "500000",
        "--max-estimated-usd",
        "5",
    ]
    assert cli.main(common) == 0
    output = capsys.readouterr().out
    assert "max_budget_usd=2.500000" in output
    assert "Approved local preflight estimate: $5.000000" in output

    assert cli.main([*common, "--execute"]) == 2
    assert "requires --confirm-paid" in capsys.readouterr().err
