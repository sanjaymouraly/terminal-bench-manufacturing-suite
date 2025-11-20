from __future__ import annotations

from pathlib import Path

import pytest

from manufacturing_bench.database import RunStore
from manufacturing_bench.providers import (
    PROVIDER_PRESETS,
    check_budget,
    estimate_cost,
    provider_statuses,
    write_provider_config,
)
from manufacturing_bench.reporting import export_report
from manufacturing_bench.util import BenchError, project_root


def test_easy_connect_writes_ignored_config_without_secrets(tmp_path: Path) -> None:
    target = write_provider_config(
        tmp_path,
        name="chatgpt",
        preset="openai",
        model="gpt-4.1-mini",
    )
    text = target.read_text(encoding="utf-8")
    assert target == tmp_path / "configs" / "providers.local.toml"
    assert "[providers.chatgpt]" in text
    assert "OPENAI_API_KEY" in text
    assert "sk-" not in text
    assert "default_model" in text
    assert "openai" in PROVIDER_PRESETS
    with pytest.raises(BenchError, match="Dated pricing"):
        write_provider_config(
            tmp_path,
            name="priced",
            preset="openai",
            input_usd_per_million=1.0,
        )
    with pytest.raises(BenchError, match="may contain only"):
        write_provider_config(tmp_path, name="bad name", preset="openai")


def test_cli_provider_presets_are_discoverable(capsys) -> None:
    from manufacturing_bench import cli

    assert cli.main(["providers", "presets"]) == 0
    output = capsys.readouterr().out
    for preset in ("openai", "anthropic", "openrouter", "custom", "ollama"):
        assert f'"{preset}"' in output


def test_report_export_handles_empty_ledger(tmp_path: Path) -> None:
    root = tmp_path / "suite"
    root.mkdir()
    RunStore(root / ".mfgbench" / "runs.sqlite3")
    for suffix in ("json", "csv", "html"):
        report = export_report(root, root / f"report.{suffix}", suffix)
        assert report.is_file()
        assert report.stat().st_size > 0


def test_example_provider_config_is_offline_and_secret_free() -> None:
    statuses = provider_statuses(project_root())
    names = {item.name for item in statuses}
    assert {"openai", "anthropic", "openrouter", "custom", "ollama"} <= names
    assert all(item.kind for item in statuses)
    assert all(not item.base_url or "api_key" not in item.base_url.lower() for item in statuses)


def test_budget_check_requires_explicit_plans_and_rejects_excess() -> None:
    pricing = {
        "input_usd_per_million": 2.0,
        "output_usd_per_million": 6.0,
        "pricing_as_of": "2026-10-18",
    }
    with pytest.raises(BenchError, match="dated cost rate"):
        estimate_cost(
            {"input_usd_per_million": 2.0, "output_usd_per_million": 6.0},
            input_tokens=1,
            output_tokens=1,
        )

    approved = check_budget(
        pricing,
        planned_input_tokens=1_000_000,
        planned_output_tokens=500_000,
        max_input_tokens=1_000_000,
        max_output_tokens=500_000,
        max_estimated_usd=5.0,
    )
    assert approved.estimated_usd == 5.0

    with pytest.raises(BenchError, match="Planned input"):
        check_budget(
            pricing,
            planned_input_tokens=101,
            planned_output_tokens=1,
            max_input_tokens=100,
            max_output_tokens=None,
            max_estimated_usd=None,
        )
    with pytest.raises(BenchError, match="requires both"):
        check_budget(
            pricing,
            planned_input_tokens=100,
            planned_output_tokens=None,
            max_input_tokens=None,
            max_output_tokens=None,
            max_estimated_usd=1.0,
        )
    with pytest.raises(BenchError, match="exceeds the cap"):
        check_budget(
            pricing,
            planned_input_tokens=1_000_000,
            planned_output_tokens=500_000,
            max_input_tokens=None,
            max_output_tokens=None,
            max_estimated_usd=4.99,
        )
