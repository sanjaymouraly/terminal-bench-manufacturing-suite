# Final completion report — 2026-10-19

## Delivered

A complete, offline-first implementation of the requested manufacturing benchmark suite:

| Task | Domain |
|---|---|
| `supplier-reconciliation` | Supplier three-way match and AP control |
| `inventory-corruption-recovery` | Event-sourced inventory recovery |
| `manufacturing-cost-variance` | Industrial cost-variance investigation |
| `bom-consistency-audit` | Time-effective BOM and ECN audit |
| `production-data-repair` | MES/ERP/PLC/QMS traceability repair |

Each standalone package contains:

- deterministic synthetic public inputs;
- an agent-facing instruction with explicit schemas, ordering and accounting policy;
- Harbor `1.0`-schema `task.toml` with separate verifier and declared artifacts;
- a non-root agent Dockerfile containing data only;
- an executable Oracle (`solve.sh` + `solve.py`) that computes from inputs;
- a separate verifier image with pristine private inputs;
- a semantic verifier and default-deny reward entrypoint;
- reviewer-facing README sections deliberately marked for human completion.

Suite infrastructure includes:

- `mfgbench` CLI: task listing/validation, fixture generation, Oracle/NOP/mutation runs, smoke suite, run inspection, Harbor import, reports, provider checks, safe cleanup and toolchain status;
- SQLite run ledger and static HTML/CSV/JSON reports with baseline and agent-trial separation;
- seeded `dev`/`eval`/`stress` fixture profiles;
- opt-in provider configuration for OpenAI, Anthropic, OpenRouter, custom OpenAI-compatible and local Ollama/vLLM endpoints;
- paid-run preflight gates: dated pricing, token/USD caps, explicit confirmation;
- CI workflows for lint, strict types, tests, fixture determinism, Docker builds and native Harbor rewards;
- real screenshots, architecture diagrams, platform setup, security and contribution documentation.

## Observed verification

| Check | Observed result |
|---|---|
| `ruff check src tests scripts tasks` | Passed |
| `ruff format --check src tests scripts tasks` | Passed; 60 files |
| `mypy` strict | Passed; 17 source files |
| `python scripts/typecheck_tasks.py` | Passed; 15 task programs |
| `python -m compileall -q src tests scripts tasks` | Passed |
| `pytest -q` | 21 passed, 1 skipped on Windows (POSIX shell entrypoint; exercised in Docker) |
| `mfgbench tasks validate` | Passed with five human-authorship warnings |
| `mfgbench smoke --concurrency 3` | 15/15 baseline contracts: Oracle 1.0, NOP 0.0, mutation 0.0 |
| Native Harbor 0.24.0 + Docker 29.8.2 | 10/10 trials: five Oracle 1.0, five NOP 0.0, all separate-verifier mode |
| Agent image inspection | UID 10001; only `/app/data`; `/solution` and `/tests` absent |
| Local Ollama | HTTP 200; `gemma3:1b`, `qwen3.5:4b` discovered |
| `uv lock --check` | Passed |
| `uv build` | sdist and wheel built |

The local mutation is schema-valid: it changes one monetary or quantity field, not the whole file. Its rejection verifies semantic grading.

## Real evidence

The following are genuine captures, not rendered SVG mockups:

- `docs/images/cli-overview.png` — Windows Terminal, tasks and validation;
- `docs/images/cli-smoke.png` — Windows Terminal, 15/15 baseline contract;
- `docs/images/harbor-oracle.png` — Windows Terminal, native Harbor Oracle reward 1.0;
- `docs/images/cli-providers.png` — Windows Terminal, live Ollama connectivity and model discovery;
- `docs/images/report-dashboard.png` — browser capture of the generated HTML report.

Native Harbor trial metadata is retained under `reports/evidence/harbor/`, with a compact summary in `reports/evidence/harbor-summary.json`.

## Correctness and fairness improvements in this revision

- Replaced full-object equality with semantic validation so free-text `detail`, `policy`, `rounding_policy`, `action` and `evidence` fields are not hidden expected answers.
- Added tests that reword free text (must still pass) and tamper a structured value (must fail).
- Removed scenario-specific hardcoding from BOM and production solvers.
- Implemented multi-node cycle detection and preserved source components through substitution slices.
- Added explicit conflicting-duplicate and stale-PLC evidence columns and generalized audit construction.
- Scaled evaluation fixtures across suppliers, currencies, periods, warehouses, lots, assemblies, orders and events.
- Added Harbor job import that ignores the job-level summary and reads only trial outcomes.
- Added real screenshots, CI workflows and corrected verification claims.

## Explicitly not claimed

1. Linux/macOS native execution was not performed in this workspace. CI configuration exists; its external run is not claimed.
2. No paid provider credentials were supplied, so no paid model, Codex/Claude/Terminus trial, token accounting or agent pass@k is claimed. Ollama connectivity is verified, but small local models are not presented as capable solvers.
3. No upstream maintainer review, PR merge or Terminal-Bench acceptance is claimed.
4. Reviewer-facing upstream README prose and agent instructions still require qualified human authorship. The instructions here are AI-assisted technical drafts, not human-authored submissions.
5. The Oracle and private reference programs are separate files but share authoring lineage; the verifier recomputes from pristine inputs and never trusts agent claims. This is documented as a maintainability limitation.

## Reproduction commands

```bash
python -m pip install -e ".[dev]"
mfgbench tasks validate
mfgbench smoke --concurrency 3
pytest -q
harbor run -p tasks/supplier-reconciliation -a oracle
harbor run -p tasks/supplier-reconciliation -a nop
mfgbench report --format html --output reports/latest.html
```

## External next steps

1. Run the GitHub Docker workflow on a Linux runner and preserve its artifact.
2. Complete human-authored reviewer sections and author metadata.
3. Conduct paid agent trials only after approving provider pricing and budget limits.
4. If proposing upstream, do so per task and record maintainer feedback truthfully.
