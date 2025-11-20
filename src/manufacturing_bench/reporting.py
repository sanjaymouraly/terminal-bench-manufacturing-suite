from __future__ import annotations

import csv
import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .database import RunStore
from .util import write_json


def _observed_sum(values: list[dict[str, Any]], field: str) -> int | float | None:
    """Sum observed numeric telemetry without inventing values for absent fields."""
    observed = [value[field] for value in values if value.get(field) is not None]
    return sum(observed) if observed else None


def _display_telemetry(value: int | float | None, *, precision: int = 0) -> str:
    if value is None:
        return "—"
    if precision:
        return f"{value:.{precision}f}"
    return str(value)


def _pass_at_k(trials: int, passes: int, k: int = 5) -> float | None:
    """Unbiased pass@k estimator for independent trials with c successes."""
    if trials <= 0:
        return None
    k = min(k, trials)
    if passes <= 0:
        return 0.0
    if trials - passes < k:
        return 1.0
    failures = trials - passes
    # P(no success in k draws) = C(failures, k) / C(trials, k)
    numerator = 1
    denominator = 1
    for index in range(k):
        numerator *= failures - index
        denominator *= trials - index
    return round(1.0 - numerator / denominator, 6)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        per_task[str(row["task"])].append(row)
    baseline_agents = {"oracle", "nop", "mutation"}
    tasks = []
    baseline = []
    agent_trials = []
    for task, values in sorted(per_task.items()):
        scores = [float(item["score"]) for item in values]
        passed = sum(1 for item in values if item["passed"])
        tasks.append(
            {
                "task": task,
                "trials": len(values),
                "passes": passed,
                "pass_rate": round(passed / len(values), 4),
                "pass_at_5": _pass_at_k(len(values), passed, 5),
                "mean_reward": round(sum(scores) / len(scores), 4),
                "mean_elapsed_seconds": round(
                    sum(float(item["elapsed_seconds"]) for item in values) / len(values), 4
                ),
                "input_tokens": _observed_sum(values, "input_tokens"),
                "cache_tokens": _observed_sum(values, "cache_tokens"),
                "output_tokens": _observed_sum(values, "output_tokens"),
                "cost_usd": _observed_sum(values, "cost_usd"),
                "failure_categories": dict(
                    sorted(
                        (
                            category,
                            sum(1 for item in values if item.get("failure_category") == category),
                        )
                        for category in {item.get("failure_category") for item in values}
                        if category
                    )
                ),
            }
        )
        by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in values:
            by_agent[str(item["agent"])].append(item)
        baseline.append(
            {
                "task": task,
                "oracle_passes": sum(1 for item in by_agent.get("oracle", []) if item["passed"]),
                "oracle_trials": len(by_agent.get("oracle", [])),
                "nop_passes": sum(1 for item in by_agent.get("nop", []) if item["passed"]),
                "nop_trials": len(by_agent.get("nop", [])),
                "mutation_passes": sum(
                    1 for item in by_agent.get("mutation", []) if item["passed"]
                ),
                "mutation_trials": len(by_agent.get("mutation", [])),
                "contract_ok": bool(by_agent.get("oracle"))
                and all(item["passed"] for item in by_agent.get("oracle", []))
                and bool(by_agent.get("nop"))
                and not any(item["passed"] for item in by_agent.get("nop", []))
                and bool(by_agent.get("mutation"))
                and not any(item["passed"] for item in by_agent.get("mutation", [])),
            }
        )
        external = [item for item in values if str(item["agent"]) not in baseline_agents]
        if external:
            external_passes = sum(1 for item in external if item["passed"])
            agent_trials.append(
                {
                    "task": task,
                    "trials": len(external),
                    "passes": external_passes,
                    "pass_rate": round(external_passes / len(external), 4),
                    "pass_at_5": _pass_at_k(len(external), external_passes, 5),
                    "mean_reward": round(
                        sum(float(item["score"]) for item in external) / len(external), 4
                    ),
                    "mean_elapsed_seconds": round(
                        sum(float(item["elapsed_seconds"]) for item in external) / len(external), 4
                    ),
                    "input_tokens": _observed_sum(external, "input_tokens"),
                    "output_tokens": _observed_sum(external, "output_tokens"),
                    "cost_usd": _observed_sum(external, "cost_usd"),
                    "failure_categories": dict(
                        sorted(
                            (
                                category,
                                sum(
                                    1
                                    for item in external
                                    if item.get("failure_category") == category
                                ),
                            )
                            for category in {item.get("failure_category") for item in external}
                            if category
                        )
                    ),
                }
            )
    return {
        "runs": rows,
        "summary": tasks,
        "baseline": baseline,
        "agent_trials": agent_trials,
    }


def export_report(root: Path, output: Path, report_format: str) -> Path:
    rows = RunStore(root / ".mfgbench" / "runs.sqlite3").all_runs()
    payload = summarise(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    if report_format == "json":
        write_json(output, payload)
    elif report_format == "csv":
        fields = [
            "run_id",
            "task",
            "task_version",
            "fixture_seed",
            "agent",
            "model",
            "score",
            "passed",
            "status",
            "failure_category",
            "started_at",
            "elapsed_seconds",
            "input_tokens",
            "cache_tokens",
            "output_tokens",
            "cost_usd",
            "artifact_dir",
            "harbor_version",
        ]
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    elif report_format == "html":
        _write_html(output, payload)
    else:
        raise ValueError(f"Unknown report format: {report_format}")
    return output


def _write_html(path: Path, payload: dict[str, Any]) -> None:
    baseline_rows = (
        "\n".join(
            "<tr>"
            f"<td>{html.escape(item['task'])}</td>"
            f"<td>{item['oracle_passes']}/{item['oracle_trials']}</td>"
            f"<td>{item['nop_passes']}/{item['nop_trials']}</td>"
            f"<td>{item['mutation_passes']}/{item['mutation_trials']}</td>"
            f"<td class={'pass' if item['contract_ok'] else 'fail'}>"
            f"{'PASS' if item['contract_ok'] else 'FAIL'}</td>"
            "</tr>"
            for item in payload.get("baseline", [])
        )
        or "<tr><td colspan='5'>No baseline trials recorded.</td></tr>"
    )
    agent_trial_rows = (
        "\n".join(
            "<tr>"
            f"<td>{html.escape(item['task'])}</td><td>{item['trials']}</td>"
            f"<td>{item['passes']}</td><td>{item['pass_rate']:.0%}</td>"
            f"<td>{'' if item.get('pass_at_5') is None else item['pass_at_5']}</td>"
            f"<td>{item['mean_reward']:.3f}</td><td>{item['mean_elapsed_seconds']:.3f}s</td>"
            f"<td>{_display_telemetry(item['input_tokens'])}</td>"
            f"<td>{_display_telemetry(item['output_tokens'])}</td>"
            f"<td>{_display_telemetry(item['cost_usd'], precision=6)}</td>"
            f"<td>{html.escape(json.dumps(item['failure_categories'], sort_keys=True))}</td>"
            "</tr>"
            for item in payload.get("agent_trials", [])
        )
        or "<tr><td colspan='11'>No external agent trials recorded. Run an agent through Harbor to populate this table.</td></tr>"
    )
    task_rows = (
        "\n".join(
            "<tr>"
            f"<td>{html.escape(item['task'])}</td><td>{item['trials']}</td><td>{item['passes']}</td>"
            f"<td>{item['pass_rate']:.0%}</td><td>{item['mean_reward']:.3f}</td>"
            f"<td>{item['mean_elapsed_seconds']:.3f}</td>"
            f"<td>{_display_telemetry(item['input_tokens'])}</td>"
            f"<td>{_display_telemetry(item['output_tokens'])}</td>"
            f"<td>{_display_telemetry(item['cost_usd'], precision=6)}</td>"
            f"<td>{html.escape(json.dumps(item['failure_categories'], sort_keys=True))}</td>"
            "</tr>"
            for item in payload["summary"]
        )
        or "<tr><td colspan='10'>No local runs have been recorded.</td></tr>"
    )
    mode_totals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in payload["runs"]:
        mode_totals[str(row["agent"])].append(row)
    mode_rows = (
        "\n".join(
            "<tr>"
            f"<td>{html.escape(agent)}</td><td>{len(values)}</td>"
            f"<td>{sum(1 for item in values if item['passed'])}</td>"
            f"<td>{sum(float(item['score']) for item in values) / len(values):.3f}</td>"
            f"<td>{sum(float(item['elapsed_seconds']) for item in values) / len(values):.3f}s</td>"
            "</tr>"
            for agent, values in sorted(mode_totals.items())
        )
        or "<tr><td colspan='5'>No records.</td></tr>"
    )
    run_rows = (
        "\n".join(
            "<tr>"
            f"<td><code>{html.escape(str(item['run_id']))}</code></td>"
            f"<td>{html.escape(str(item['task']))}</td><td>{html.escape(str(item['agent']))}</td>"
            f"<td class={'pass' if item['passed'] else 'fail'}>{item['score']:.1f}</td>"
            f"<td>{html.escape(str(item['status']))}</td><td>{item['elapsed_seconds']:.3f}s</td>"
            f"<td>{_display_telemetry(item.get('input_tokens'))}</td>"
            f"<td>{_display_telemetry(item.get('output_tokens'))}</td>"
            f"<td>{_display_telemetry(item.get('cost_usd'), precision=6)}</td>"
            f"<td>{html.escape(str(item['started_at']))}</td></tr>"
            for item in payload["runs"][:20]
        )
        or "<tr><td colspan='10'>No records.</td></tr>"
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Manufacturing Bench report</title>
<style>
:root{{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#0b1220;color:#e5edf9}}
body{{max-width:1280px;margin:0 auto;padding:2rem}}h1{{margin-bottom:.2rem}}p{{color:#a9bad4}}
.card{{background:#111c30;border:1px solid #2b3d59;border-radius:12px;padding:1.25rem;margin:1rem 0;overflow:auto}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{border-bottom:1px solid #283a55;padding:.65rem;text-align:left;white-space:nowrap}}th{{color:#8ab4f8}}.pass{{color:#67e8a9;font-weight:700}}.fail{{color:#ff9f9f;font-weight:700}}code{{font-size:.8rem}}
.badge{{display:inline-block;padding:.15rem .5rem;border-radius:999px;background:#16243b;color:#8ab4f8;font-size:.75rem;margin-left:.4rem}}
</style></head><body>
<h1>Terminal-Bench Manufacturing Suite</h1>
<p>Observed local and Harbor runs from the immutable SQLite ledger. Baseline rows are deliberately separated from external agent trials.</p>
<section class="card"><h2>Baseline contract <span class="badge">oracle=1 · nop=0 · mutation=0</span></h2>
<table><thead><tr><th>Task</th><th>Oracle passes</th><th>NOP passes</th><th>Mutation passes</th><th>Contract</th></tr></thead><tbody>{baseline_rows}</tbody></table></section>
<section class="card"><h2>Agent trials</h2><table><thead><tr><th>Task</th><th>Trials</th><th>Passes</th><th>Pass rate</th><th>Pass@5</th><th>Mean reward</th><th>Mean time</th><th>Input tokens</th><th>Output tokens</th><th>Cost USD</th><th>Failure categories</th></tr></thead><tbody>{agent_trial_rows}</tbody></table></section>
<section class="card"><h2>Trial volume by mode</h2><table><thead><tr><th>Mode</th><th>Trials</th><th>Passes</th><th>Mean reward</th><th>Mean time</th></tr></thead><tbody>{mode_rows}</tbody></table></section>
<section class="card"><h2>Per-task totals (all modes)</h2><table><thead><tr><th>Task</th><th>Trials</th><th>Passes</th><th>Pass rate</th><th>Mean reward</th><th>Mean time</th><th>Input tokens</th><th>Output tokens</th><th>Cost USD</th><th>Failure categories</th></tr></thead><tbody>{task_rows}</tbody></table></section>
<section class="card"><h2>Trial detail <span class="badge">latest 20</span></h2><table><thead><tr><th>Run</th><th>Task</th><th>Agent</th><th>Reward</th><th>Status</th><th>Elapsed</th><th>Input tokens</th><th>Output tokens</th><th>Cost USD</th><th>Started</th></tr></thead><tbody>{run_rows}</tbody></table></section>
</body></html>"""
    path.write_text(page, encoding="utf-8")
