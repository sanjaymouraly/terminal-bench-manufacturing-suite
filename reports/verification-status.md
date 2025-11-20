# Observed verification status — 2026-10-19

This file records commands actually run in the build workspace. It distinguishes native Harbor/Docker execution from the offline local harness and does not claim unexecuted work.

## Toolchain observed

| Item | Observed result |
|---|---|
| OS | Windows 11, PowerShell 5.1 |
| Python | 3.14.8 |
| uv | 0.13.1 |
| Harbor | 0.24.0 (`pip install harbor`) |
| Docker | 29.8.2, Docker Desktop containerized engine |
| Test host | Docker Desktop on Windows, Linux containers |

## Offline task contract

Command:

```text
mfgbench smoke --concurrency 3
```

Late in the build the smoke was run twice after fixture scaling and after the semantic mutator was introduced. All runs produced the same contract:

| Task | Oracle | NOP | Schema-valid semantic mutation | Contract |
|---|---:|---:|---:|---|
| `supplier-reconciliation` | 1.0 | 0.0 | 0.0 | PASS |
| `inventory-corruption-recovery` | 1.0 | 0.0 | 0.0 | PASS |
| `manufacturing-cost-variance` | 1.0 | 0.0 | 0.0 | PASS |
| `bom-consistency-audit` | 1.0 | 0.0 | 0.0 | PASS |
| `production-data-repair` | 1.0 | 0.0 | 0.0 | PASS |

The mutation is not a malformed file. It changes one monetary or quantity field while preserving the declared schema; rejection demonstrates semantic verification rather than filename checks.

Screenshots (real Windows Terminal captures):

- [`../docs/images/cli-overview.png`](../docs/images/cli-overview.png)
- [`../docs/images/cli-smoke.png`](../docs/images/cli-smoke.png)
- [`../docs/images/cli-providers.png`](../docs/images/cli-providers.png)

## Native Harbor / Docker validation

Commands (five tasks, Oracle and NOP):

```text
harbor run -p tasks/<task> -a oracle -o jobs
harbor run -p tasks/<task> -a nop    -o jobs
```

Observed results:

| Task | Oracle reward | NOP reward | Trials | Verifier mode |
|---|---:|---:|---:|---|
| supplier-reconciliation | 1.0 | 0.0 | 1 + 1 | separate |
| inventory-corruption-recovery | 1.0 | 0.0 | 1 + 1 | separate |
| manufacturing-cost-variance | 1.0 | 0.0 | 1 + 1 | separate |
| bom-consistency-audit | 1.0 | 0.0 | 1 + 1 | separate |
| production-data-repair | 1.0 | 0.0 | 1 + 1 | separate |

A final ten-trial pass was rerun after the task packages were frozen; all ten trials had zero Harbor exceptions and used the final checked-in instructions and fixtures. Oracle runtimes were approximately 24-32 seconds including image build/startup; NOP runtimes were approximately 18-24 seconds.

Evidence: [`evidence/harbor-summary.json`](evidence/harbor-summary.json) and retained trial directories under [`evidence/harbor/`](evidence/harbor/).

Screenshot: [`../docs/images/harbor-oracle.png`](../docs/images/harbor-oracle.png).

## Agent image isolation

A representative agent image was built and inspected directly:

```text
docker build -q -t mfgbench-env-check tasks/supplier-reconciliation/environment
docker run --rm mfgbench-env-check sh -c "id; find /app -maxdepth 3 -type f; test ! -e /solution; test ! -e /tests"
```

Observed:

- `uid=10001(bench) gid=10001(bench)`
- only `/app/data/*` files present under `/app`
- `/solution` absent
- `/tests` absent

## Full offline regression

| Command | Observed result |
|---|---|
| `ruff check src tests scripts tasks` | All checks passed |
| `ruff format --check src tests scripts tasks` | 60 files already formatted |
| `mypy` (strict) | Success: no issues in 17 source files |
| `python scripts/typecheck_tasks.py` | Strict mypy passed for 15 standalone task programs |
| `python -m compileall -q src tests scripts tasks` | Passed |
| `pytest -q` | **21 passed, 1 skipped** |
| `mfgbench tasks validate` | Passed with five intentional human-authorship warnings |
| `uv lock --check` | Passed |
| `uv build` | Built sdist and universal wheel |
| `mfgbench providers validate` | Passed; Ollama configured, paid providers unconfigured |

The skipped test is the POSIX `test.sh` reward-file entrypoint, which requires `sh`. The same entrypoint was executed successfully inside the Harbor verifier container on every task, so this is a Windows-host limitation rather than an untested production path.

## Provider connectivity

Observed with a local Ollama service:

```text
mfgbench providers test ollama --network
  endpoint: http://127.0.0.1:11434/v1/models
  http_status: 200
  reachable: true

mfgbench providers models ollama --network
  models: ["gemma3:1b", "qwen3.5:4b"]
```

No paid provider key was supplied. No paid generation, paid agent trial, external agent pass@k or API cost is claimed.

## Reporting

`mfgbench runs import-harbor` imported the ten native Harbor trial outcomes into the SQLite ledger. Local smoke runs were also recorded. The HTML/CSV/JSON exports were generated from those observed rows and the baseline contract table was separated from external agent trials.

Screenshot: [`../docs/images/report-dashboard.png`](../docs/images/report-dashboard.png).

## Not run / external blockers

- Linux/macOS native runtime was not executed in this workspace; GitHub Actions configuration is present but its external run is not claimed.
- No paid OpenAI, Anthropic, OpenRouter, custom endpoint or external agent trial was executed.
- Local Ollama gave `gemma3:1b` and `qwen3.5:4b`; these small models were not represented as capable solvers.
- No Terminal-Bench maintainer feedback, pull request, merge or upstream acceptance is claimed.
- Reviewer-facing task README sections remain explicit **HUMAN-AUTHORSHIP REQUIRED** placeholders.
