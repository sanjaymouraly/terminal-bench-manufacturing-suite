from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .database import RunStore
from .generation import generate_fixtures
from .harbor import (
    build_harbor_command,
    collect_harbor_results,
    execute_harbor,
    runtime_limit_kwargs,
    toolchain_status,
)
from .local_runner import run_local
from .models import RunResult, ValidationIssue
from .providers import (
    PROVIDER_PRESETS,
    check_budget,
    discover_models,
    estimate_cost,
    load_provider_config,
    provider_statuses,
    test_connection,
    write_provider_config,
)
from .reporting import export_report
from .tasks import list_tasks, load_task
from .util import BenchError, project_root, remove_tree_safe, slugify, utc_now
from .validator import validate_all, validate_task


def _root(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project_root()


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _cmd_tasks_list(args: argparse.Namespace) -> int:
    tasks = list_tasks(_root(args.root))
    if args.json:
        _print_json(
            [
                {
                    "slug": task.slug,
                    "name": task.name,
                    "version": task.version,
                    "seed": task.fixture_seed,
                    "tags": task.tags,
                    "artifacts": task.artifacts,
                }
                for task in tasks
            ]
        )
    else:
        print(f"{'TASK':38} {'VERSION':10} {'SEED':10} TAGS")
        for task in tasks:
            print(
                f"{task.slug:38} {task.version:10} {str(task.fixture_seed or ''):10} {', '.join(task.tags)}"
            )
    return 0


def _cmd_tasks_inspect(args: argparse.Namespace) -> int:
    task = load_task(args.task, _root(args.root))
    _print_json(
        {
            "slug": task.slug,
            "path": str(task.path),
            "name": task.name,
            "version": task.version,
            "fixture_seed": task.fixture_seed,
            "agent_timeout_sec": task.agent_timeout_sec,
            "verifier_timeout_sec": task.verifier_timeout_sec,
            "artifacts": task.artifacts,
            "tags": task.tags,
        }
    )
    return 0


def _cmd_tasks_validate(args: argparse.Namespace) -> int:
    root = _root(args.root)
    values: dict[str, list[ValidationIssue]]
    if args.task:
        task = load_task(args.task, root)
        values = {task.slug: validate_task(task.path, upstream=args.upstream)}
    else:
        values = validate_all(root, upstream=args.upstream)
    errors = 0
    output: dict[str, list[dict[str, str]]] = {}
    for slug, issues in values.items():
        output[slug] = [item.to_dict() for item in issues]
        errors += sum(1 for item in issues if item.level == "error")
    if args.json:
        _print_json(output)
    else:
        for slug, serialized_issues in output.items():
            print(f"{slug}:")
            if not serialized_issues:
                print("  OK")
            for issue in serialized_issues:
                print(f"  {issue['level'].upper():7} {issue['code']}: {issue['message']}")
    return 1 if errors else 0


def _result_line(result: RunResult) -> None:
    print(
        f"{result.task:38} {result.agent:9} reward={result.score:.1f} "
        f"status={result.status} elapsed={result.elapsed_seconds:.3f}s run={result.run_id}"
    )


def _cmd_run(args: argparse.Namespace) -> int:
    root = _root(args.root)
    result = run_local(
        args.task,
        agent=args.agent,
        root=root,
        model=args.model,
        runs_dir=Path(args.runs_dir).resolve() if args.runs_dir else None,
        keep_workspace=not args.drop_workspace,
    )
    _result_line(result)
    if args.json:
        _print_json(result.to_dict())
    return 0


def _smoke_one(root: Path, task: str) -> tuple[str, list[RunResult]]:
    results = [
        run_local(task, agent="oracle", root=root),
        run_local(task, agent="nop", root=root),
        run_local(task, agent="mutation", root=root),
    ]
    return task, results


def _cmd_smoke(args: argparse.Namespace) -> int:
    root = _root(args.root)
    names = [args.task] if args.task else [item.slug for item in list_tasks(root)]
    complete: list[tuple[str, list[RunResult]]] = []
    workers = max(1, min(args.concurrency, len(names)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_smoke_one, root, name) for name in names]
        for future in futures:
            complete.append(future.result())
    expected_ok = True
    for name, results in sorted(complete):
        oracle, nop, mutation = results
        for item in results:
            _result_line(item)
        condition = oracle.score == 1.0 and nop.score == 0.0 and mutation.score == 0.0
        print(f"  {'PASS' if condition else 'FAIL'} baseline contract for {name}")
        expected_ok = expected_ok and condition
    return 0 if expected_ok else 1


def _cmd_generate(args: argparse.Namespace) -> int:
    root = _root(args.root)
    if args.write_canonical and args.target:
        raise BenchError("Use either --write-canonical or --target, not both.")
    target = Path(args.target).expanduser().resolve() if args.target else None
    generate_fixtures(
        root,
        task=args.task,
        profile=args.profile,
        target=target,
        write_canonical=args.write_canonical,
    )
    print("Fixture generation completed.")
    return 0


def _cmd_runs_list(args: argparse.Namespace) -> int:
    root = _root(args.root)
    rows = RunStore(root / ".mfgbench" / "runs.sqlite3").list_runs(task=args.task, limit=args.limit)
    if args.json:
        _print_json(rows)
    else:
        print(f"{'RUN':32} {'TASK':34} {'AGENT':10} {'REWARD':7} STATUS")
        for row in rows:
            print(
                f"{row['run_id']:32} {row['task']:34} {row['agent']:10} {row['score']:<7.1f} {row['status']}"
            )
    return 0


def _cmd_runs_import_harbor(args: argparse.Namespace) -> int:
    root = _root(args.root)
    task = load_task(args.task, root)
    job_dir = Path(args.job_dir).expanduser()
    if not job_dir.is_absolute():
        job_dir = root / job_dir
    if not job_dir.is_dir():
        raise BenchError(f"Harbor job directory does not exist: {job_dir}")
    imported = collect_harbor_results(
        job_dir,
        root=root,
        task=task.slug,
        task_version=task.version,
        fixture_seed=task.fixture_seed,
        fallback_agent=args.agent,
        fallback_model=args.model,
        command=["harbor", "run", "-p", str(task.path), "-a", args.agent],
        fallback_started_at=utc_now(),
    )
    if not imported:
        raise BenchError(
            "No readable Harbor trial result.json files were found in the given job directory."
        )
    store = RunStore(root / ".mfgbench" / "runs.sqlite3")
    version = toolchain_status().harbor_version
    for result in imported:
        store.record(result, version)
    print(f"Imported {len(imported)} observed Harbor trial result(s) into the local ledger.")
    for result in imported:
        _result_line(result)
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    root = _root(args.root)
    store = RunStore(root / ".mfgbench" / "runs.sqlite3")
    record = store.get_run(args.run_id)
    if not record:
        raise BenchError(f"Run does not exist: {args.run_id}")
    run_dir = root / record["artifact_dir"]
    analysis = {
        "run_id": args.run_id,
        "task": record["task"],
        "score": record["score"],
        "classification": record["failure_category"] or "success",
        "status": record["status"],
        "reproducibility": {
            "task_version": record["task_version"],
            "fixture_seed": record["fixture_seed"],
            "harbor_version": record["harbor_version"],
            "artifact_dir_exists": run_dir.exists(),
        },
        "diagnostics": record["diagnostics"],
        "available_logs": [item.name for item in run_dir.glob("*.log")] if run_dir.is_dir() else [],
    }
    _print_json(analysis)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path = Path(args.output).expanduser()
    if not path.is_absolute():
        path = root / path
    generated = export_report(root, path, args.format)
    print(f"Wrote {args.format.upper()} report: {generated}")
    return 0


def _cmd_providers_validate(args: argparse.Namespace) -> int:
    root = _root(args.root)
    config = Path(args.config).expanduser() if args.config else None
    statuses = provider_statuses(root, config)
    _print_json(
        [
            {
                "name": item.name,
                "kind": item.kind,
                "base_url": item.base_url,
                "configured": item.configured,
                "paid": item.paid,
                "diagnostics": item.diagnostics,
            }
            for item in statuses
        ]
    )
    if args.require:
        required = next((item for item in statuses if item.name == args.require), None)
        return 0 if required and required.configured else 2
    return 0


def _cmd_providers_presets(args: argparse.Namespace) -> int:
    _print_json(
        {
            name: {key: value for key, value in preset.items()}
            for name, preset in sorted(PROVIDER_PRESETS.items())
        }
    )
    return 0


def _cmd_providers_add(args: argparse.Namespace) -> int:
    root = _root(args.root)
    target = write_provider_config(
        root,
        name=args.name,
        preset=args.preset,
        base_url=args.base_url,
        base_url_env=args.base_url_env,
        api_key_env=args.api_key_env,
        model=args.model,
        paid=args.paid,
        input_usd_per_million=args.input_usd_per_million,
        output_usd_per_million=args.output_usd_per_million,
        pricing_as_of=args.pricing_as_of,
    )
    statuses = provider_statuses(root, target)
    selected = next((item for item in statuses if item.name == args.name), None)
    _print_json(
        {
            "config": str(target),
            "provider": args.name,
            "configured": selected.configured if selected else False,
            "diagnostics": list(selected.diagnostics) if selected else [],
            "next": f"mfgbench providers test {args.name} --network",
        }
    )
    return 0


def _cmd_providers_test(args: argparse.Namespace) -> int:
    root = _root(args.root)
    if not args.network:
        raise BenchError(
            "Connection testing is networked. Re-run with --network after reviewing the endpoint."
        )
    result = test_connection(
        root, args.provider, Path(args.config).expanduser() if args.config else None
    )
    _print_json(result)
    return 0 if result.get("reachable") else 3


def _cmd_providers_models(args: argparse.Namespace) -> int:
    root = _root(args.root)
    if not args.network:
        raise BenchError(
            "Model discovery is networked. Re-run with --network after reviewing the endpoint."
        )
    models = discover_models(
        root, args.provider, Path(args.config).expanduser() if args.config else None
    )
    _print_json({"provider": args.provider, "models": models})
    return 0


def _cmd_providers_estimate(args: argparse.Namespace) -> int:
    root = _root(args.root)
    config = load_provider_config(root, Path(args.config).expanduser() if args.config else None)
    if args.provider not in config:
        raise BenchError(f"Provider not found: {args.provider}")
    usd = estimate_cost(
        config[args.provider], input_tokens=args.input_tokens, output_tokens=args.output_tokens
    )
    _print_json(
        {
            "provider": args.provider,
            "estimated_usd": round(usd, 6),
            "pricing_source": "local configuration",
        }
    )
    return 0


def _cmd_harbor_run(args: argparse.Namespace) -> int:
    root = _root(args.root)
    task = load_task(args.task, root)
    if args.attempts < 1:
        raise BenchError("--attempts must be at least 1.")
    if args.max_infrastructure_retries < 0 or args.retry_delay_seconds < 0:
        raise BenchError("Retry values must be non-negative.")
    if args.max_agent_timeout_seconds is not None:
        if args.max_agent_timeout_seconds <= 0:
            raise BenchError("--max-agent-timeout-seconds must be positive.")
        if args.max_agent_timeout_seconds > task.agent_timeout_sec:
            raise BenchError(
                f"--max-agent-timeout-seconds cannot exceed the task limit of {task.agent_timeout_sec:g}."
            )
        agent_timeout_multiplier = args.max_agent_timeout_seconds / task.agent_timeout_sec
    else:
        agent_timeout_multiplier = None

    budget_flags_used = any(
        value is not None
        for value in (
            args.planned_input_tokens,
            args.planned_output_tokens,
            args.max_input_tokens,
            args.max_output_tokens,
            args.max_estimated_usd,
        )
    )
    provider_is_paid = False
    budget = None
    if args.provider:
        provider_config_path = (
            Path(args.provider_config).expanduser() if args.provider_config else None
        )
        provider_config = load_provider_config(root, provider_config_path)
        statuses = {item.name: item for item in provider_statuses(root, provider_config_path)}
        selected_provider = statuses.get(args.provider)
        if args.provider not in provider_config or selected_provider is None:
            raise BenchError(f"Provider not found in the selected configuration: {args.provider}")
        provider_is_paid = selected_provider.paid
        if args.execute and not selected_provider.configured:
            raise BenchError(
                f"Provider {args.provider} is not configured: "
                f"{'; '.join(selected_provider.diagnostics)}"
            )
        budget = check_budget(
            provider_config[args.provider],
            planned_input_tokens=args.planned_input_tokens,
            planned_output_tokens=args.planned_output_tokens,
            max_input_tokens=args.max_input_tokens,
            max_output_tokens=args.max_output_tokens,
            max_estimated_usd=args.max_estimated_usd,
        )
    elif budget_flags_used:
        raise BenchError(
            "Budget/token flags require --provider so pricing and safety settings are explicit."
        )

    external_agent = args.agent not in {"oracle", "nop"}
    if args.execute and external_agent:
        if not args.provider:
            raise BenchError(
                "External agent execution requires --provider to make cost and credential handling explicit."
            )
        if provider_is_paid:
            if not args.confirm_paid:
                raise BenchError(
                    "Paid execution requires --confirm-paid after reviewing the command and budget."
                )
            if args.max_estimated_usd is None:
                raise BenchError(
                    "Paid execution requires --max-estimated-usd plus planned token values and local dated rates."
                )

    agent_budget_usd = (
        args.max_estimated_usd / args.attempts
        if args.agent == "claude-code" and args.max_estimated_usd is not None
        else None
    )
    agent_kwargs = runtime_limit_kwargs(
        args.agent,
        max_turns=args.max_turns,
        max_thinking_tokens=args.max_thinking_tokens,
        max_budget_usd=agent_budget_usd,
    )
    harbor_jobs_dir = root / "runs" / "harbor"
    harbor_job_name = f"mfgbench-{slugify(task.slug)}-{uuid.uuid4().hex[:12]}"
    command = build_harbor_command(
        task.path,
        args.agent,
        args.model,
        args.attempts,
        agent_timeout_multiplier=agent_timeout_multiplier,
        agent_kwargs=agent_kwargs,
        jobs_dir=harbor_jobs_dir,
        job_name=harbor_job_name,
    )
    print("Prepared Harbor command:")
    print(" ".join(command))
    if budget and budget.estimated_usd is not None:
        print(
            "Approved local preflight estimate: "
            f"${budget.estimated_usd:.6f} for {budget.planned_input_tokens} input and "
            f"{budget.planned_output_tokens} output tokens across the requested job."
        )
    if agent_timeout_multiplier is not None:
        print(f"Agent runtime cap: {args.max_agent_timeout_seconds:g} seconds per trial.")
    if not args.execute:
        print("Dry run only. Add --execute to launch an external agent evaluation.")
        return 0

    harbor_jobs_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    exit_code = execute_harbor(
        command,
        root,
        max_infrastructure_retries=args.max_infrastructure_retries,
        retry_delay_seconds=args.retry_delay_seconds,
    )
    job_dir = harbor_jobs_dir / harbor_job_name
    imported = collect_harbor_results(
        job_dir,
        root=root,
        task=task.slug,
        task_version=task.version,
        fixture_seed=task.fixture_seed,
        fallback_agent=args.agent,
        fallback_model=args.model,
        command=command,
        fallback_started_at=started_at,
    )
    store = RunStore(root / ".mfgbench" / "runs.sqlite3")
    if imported:
        for result in imported:
            store.record(result, toolchain_status().harbor_version)
        print(
            f"Recorded {len(imported)} observed Harbor trial result(s) in the local SQLite ledger."
        )
    else:
        try:
            artifact_dir = str(job_dir.relative_to(root))
        except ValueError:
            artifact_dir = str(job_dir)
        missing_result = RunResult(
            run_id=f"{harbor_job_name}-missing-result",
            task=task.slug,
            task_version=task.version,
            fixture_seed=task.fixture_seed,
            agent=args.agent,
            model=args.model,
            score=0.0,
            passed=False,
            status="infrastructure_error",
            failure_category="harbor_result_missing",
            started_at=started_at,
            elapsed_seconds=0.0,
            artifact_dir=artifact_dir,
            command=command,
            diagnostics=["Harbor execution completed without a readable persisted trial result."],
        )
        store.record(missing_result, toolchain_status().harbor_version)
        print(
            "No readable Harbor result.json was found; recorded an infrastructure error instead.",
            file=sys.stderr,
        )
        if exit_code == 0:
            return 1
    return exit_code


def _cmd_toolchain(args: argparse.Namespace) -> int:
    status = toolchain_status()
    _print_json(
        {
            "suite_version": __version__,
            "harbor_version": status.harbor_version,
            "docker_available": status.docker_available,
            "docker_detail": status.docker_detail,
        }
    )
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    root = _root(args.root)
    targets: list[Path] = []
    if args.runs:
        targets.append(root / "runs")
    if args.state:
        targets.append(root / ".mfgbench")
    if not targets:
        raise BenchError("Choose --runs, --state, or both; clean never guesses.")
    if not args.yes:
        raise BenchError("Refusing deletion without --yes.")
    for target in targets:
        remove_tree_safe(root, target)
        print(f"Removed {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mfgbench", description="Manufacturing Harbor benchmark manager"
    )
    parser.add_argument("--root", help="suite checkout path (defaults to discovery)")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    tasks = sub.add_parser("tasks", help="list, inspect, or statically validate task packages")
    task_sub = tasks.add_subparsers(dest="task_command", required=True)
    listed = task_sub.add_parser("list")
    listed.add_argument("--json", action="store_true")
    listed.set_defaults(func=_cmd_tasks_list)
    inspect = task_sub.add_parser("inspect")
    inspect.add_argument("task")
    inspect.set_defaults(func=_cmd_tasks_inspect)
    validate = task_sub.add_parser("validate")
    validate.add_argument("task", nargs="?")
    validate.add_argument(
        "--upstream", action="store_true", help="treat human-authorship placeholders as errors"
    )
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=_cmd_tasks_validate)

    generated = sub.add_parser(
        "generate", help="deterministically generate a development/evaluation/stress fixture"
    )
    generated.add_argument("--task", help="one task slug; default regenerates all")
    generated.add_argument("--profile", choices=("dev", "eval", "stress"), default="eval")
    generated.add_argument(
        "--target", help="safe external target directory; never overwrites canonical data"
    )
    generated.add_argument(
        "--write-canonical",
        action="store_true",
        help="explicitly update checked-in eval inputs and private copies",
    )
    generated.set_defaults(func=_cmd_generate)

    run = sub.add_parser("run", help="run a local offline Oracle/NOP/mutation baseline")
    run.add_argument("task")
    run.add_argument("--agent", choices=("oracle", "nop", "mutation"), default="oracle")
    run.add_argument("--model", help="provenance label only for local runs")
    run.add_argument("--runs-dir")
    run.add_argument("--drop-workspace", action="store_true")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=_cmd_run)

    smoke = sub.add_parser("smoke", help="Oracle=1, NOP=0, mutation=0 for one task or the suite")
    smoke.add_argument("task", nargs="?")
    smoke.add_argument("--concurrency", type=int, default=1)
    smoke.set_defaults(func=_cmd_smoke)

    runs = sub.add_parser("runs", help="inspect immutable local run metadata")
    runs_sub = runs.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_sub.add_parser("list")
    runs_list.add_argument("--task")
    runs_list.add_argument("--limit", type=int, default=50)
    runs_list.add_argument("--json", action="store_true")
    runs_list.set_defaults(func=_cmd_runs_list)
    runs_import = runs_sub.add_parser(
        "import-harbor", help="import an observed Harbor job directory into the local ledger"
    )
    runs_import.add_argument("job_dir", help="Harbor job directory, relative to the suite root")
    runs_import.add_argument("--task", required=True, help="task slug the job belongs to")
    runs_import.add_argument("--agent", default="unknown", help="fallback agent label")
    runs_import.add_argument("--model", help="fallback model label")
    runs_import.set_defaults(func=_cmd_runs_import_harbor)

    analyze = sub.add_parser(
        "analyze", help="show recorded result provenance and local diagnostics"
    )
    analyze.add_argument("run_id")
    analyze.set_defaults(func=_cmd_analyze)

    report = sub.add_parser("report", help="export observed local trial results")
    report.add_argument("--format", choices=("json", "csv", "html"), default="html")
    report.add_argument("--output", required=True)
    report.set_defaults(func=_cmd_report)

    providers = sub.add_parser(
        "providers", help="offline configuration checks and opt-in model discovery"
    )
    provider_sub = providers.add_subparsers(dest="provider_command", required=True)
    ppresets = provider_sub.add_parser("presets", help="list easy-connect provider presets")
    ppresets.set_defaults(func=_cmd_providers_presets)
    padd = provider_sub.add_parser(
        "add", help="write a safe local provider entry (secrets remain in env vars)"
    )
    padd.add_argument("--name", required=True, help="local provider name, e.g. chatgpt")
    padd.add_argument("--preset", choices=tuple(sorted(PROVIDER_PRESETS)), help="provider preset")
    padd.add_argument("--base-url")
    padd.add_argument("--base-url-env")
    padd.add_argument("--api-key-env")
    padd.add_argument("--model", help="default model identifier")
    padd.add_argument("--paid", action="store_true", default=None, help="mark as paid")
    padd.add_argument("--input-usd-per-million", type=float)
    padd.add_argument("--output-usd-per-million", type=float)
    padd.add_argument("--pricing-as-of", help="ISO date for supplied pricing")
    padd.set_defaults(func=_cmd_providers_add)
    pvalidate = provider_sub.add_parser("validate")
    pvalidate.add_argument("--config")
    pvalidate.add_argument(
        "--require", help="exit nonzero unless this named provider is configured"
    )
    pvalidate.set_defaults(func=_cmd_providers_validate)
    ptest = provider_sub.add_parser(
        "test", help="explicitly test endpoint reachability without generation"
    )
    ptest.add_argument("provider")
    ptest.add_argument("--config")
    ptest.add_argument("--network", action="store_true")
    ptest.set_defaults(func=_cmd_providers_test)
    models = provider_sub.add_parser("models")
    models.add_argument("provider")
    models.add_argument("--config")
    models.add_argument("--network", action="store_true")
    models.set_defaults(func=_cmd_providers_models)
    estimate = provider_sub.add_parser("estimate-cost")
    estimate.add_argument("provider")
    estimate.add_argument("--input-tokens", type=int, required=True)
    estimate.add_argument("--output-tokens", type=int, required=True)
    estimate.add_argument("--config")
    estimate.set_defaults(func=_cmd_providers_estimate)

    harbor = sub.add_parser("harbor-run", help="prepare or explicitly launch a Harbor task trial")
    harbor.add_argument("task")
    harbor.add_argument("--agent", required=True)
    harbor.add_argument("--model")
    harbor.add_argument("--provider", help="named provider from the local provider configuration")
    harbor.add_argument("--provider-config", help="optional local provider TOML override")
    harbor.add_argument(
        "--attempts", type=int, default=1, help="maximum Harbor trials for this job"
    )
    harbor.add_argument(
        "--max-agent-timeout-seconds",
        type=float,
        help="cap each agent trial below the task's declared agent timeout",
    )
    harbor.add_argument(
        "--max-turns",
        type=int,
        help="supported Claude Code/Terminus 2 per-trial turn cap",
    )
    harbor.add_argument(
        "--max-thinking-tokens",
        type=int,
        help="supported Claude Code/Terminus 2 per-trial thinking-token cap",
    )
    harbor.add_argument(
        "--planned-input-tokens",
        type=int,
        help="operator-supplied job-wide input-token estimate used only for preflight",
    )
    harbor.add_argument(
        "--planned-output-tokens",
        type=int,
        help="operator-supplied job-wide output-token estimate used only for preflight",
    )
    harbor.add_argument(
        "--max-input-tokens",
        type=int,
        help="reject a job whose planned input estimate exceeds this cap",
    )
    harbor.add_argument(
        "--max-output-tokens",
        type=int,
        help="reject a job whose planned output estimate exceeds this cap",
    )
    harbor.add_argument(
        "--max-estimated-usd",
        type=float,
        help="job-wide preflight USD cap; paid execution requires it and reliable local rates",
    )
    harbor.add_argument(
        "--max-infrastructure-retries",
        type=int,
        default=0,
        help="retry only recognizable Docker/network infrastructure failures",
    )
    harbor.add_argument("--retry-delay-seconds", type=float, default=2.0)
    harbor.add_argument("--execute", action="store_true")
    harbor.add_argument("--confirm-paid", action="store_true")
    harbor.set_defaults(func=_cmd_harbor_run)

    toolchain = sub.add_parser("toolchain", help="show Harbor and Docker availability")
    toolchain.set_defaults(func=_cmd_toolchain)

    clean = sub.add_parser("clean", help="safely delete suite-local runtime data")
    clean.add_argument("--runs", action="store_true")
    clean.add_argument("--state", action="store_true")
    clean.add_argument("--yes", action="store_true")
    clean.set_defaults(func=_cmd_clean)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
