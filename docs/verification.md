# Verification design

## Reward semantics

Each Harbor task verifier writes `1` or `0` to `/logs/verifier/reward.txt`. The shell entrypoint starts with reward `0` (default deny), runs the Python verifier, and promotes the reward to `1` only when every check passes. The verifier parses only the declared artifacts under `/app/output`, recomputes the policy outcome from pristine inputs under `/tests/private`, and emits a diagnostic JSON result.

No verifier trusts an agent-authored status, total, hash, or narrative. Agent-provided claims in `audit.json`, `validation_report.json` or `repair_audit.json` are validated against the private recomputation or against independently checked invariants.

## Fairness rule: only specified fields are matched

The instructions define controlled fields, schemas and ordering. Free-text fields that a competent analyst must phrase independently are **not** compared with hidden prose:

| Task | Fields compared exactly or semantically | Fields required but wording-independent |
|---|---|---|
| Supplier | invoice decisions, supported/unresolved amounts, duplicate choice, status, dispute quantities/amounts, reconciliation totals | `disputes.detail`, `audit.policy` |
| Inventory | ledger rows, balances, transfer status, digest, duplicate/conflict IDs, snapshot status | `snapshot_findings.action` |
| Cost | Decimal variance decomposition, factor ranking, report totals, finding identity/variance/evidence provenance | `rounding_policy`, `accounting_policies` |
| BOM | repaired revision timeline, line slices, requirements, repair operations, findings/cycles/history | `repair_log.evidence` |
| Production | normalized history, genealogy, accounting, dispositions, repair audit and invariants | (no free-text output field) |

Tests in `tests/test_verifier_semantics.py` deliberately reword free-text fields and assert the verifier still returns `1.0`, then make a schema-valid but wrong numeric decision and assert `0.0`.

## Check matrix

| Task | Private recomputation | Independent invariants | Negative path |
|---|---|---|---|
| Supplier | aliases, duplicate choice, accepted-receipt allocation, dated contract cap, FX, tax and credits | unique invoice decisions, non-negative payables, gross - credit = net, payable IDs agree with reconciliation | missing, malformed, or one-cent/value-tampered artifact |
| Inventory | idempotent grouping, conflict quarantine, sorted replay, signed recovery evidence, transfer status | non-negative stock/reserved/available, unique idempotency keys, digest, active reservation reconciliation | missing ledger, reordered/duplicated event, tampered quantity |
| Cost | Decimal factor decomposition from raw standards and actuals | per-order factors reconcile to total variance, factor totals agree, materiality threshold | missing report, zeroed/tampered variance |
| BOM | ECN interval and quantity repair, effective substitution slices, recursive explosion, multi-node cycles | blocked order count, cycle paths, historical revision preservation, source-component preservation | missing BOM, deleted blocked order, tampered quantity |
| Production | clock normalization, duplicate/conflict resolution, stale-state override, ERP recovery, reallocation, QMS repair | output + scrap conservation, failed batch remains HOLD, unique history event IDs | missing history, erased duplicate audit, tampered accounting |

## Mutation and metamorphic coverage

`mfgbench smoke` runs each task three ways:

- Oracle must return `1.0`.
- NOP must return `0.0`.
- A **schema-valid semantic mutation** must return `0.0`. The mutator changes one monetary or quantity field after Oracle completion rather than replacing the file with junk, so the negative test exercises semantic verification.

Additional tests:

- regenerate the checked-in eval fixtures byte-for-byte;
- compare SHA-256 trees for two Oracle runs;
- permute inventory JSONL source order and require identical replay (metamorphic);
- reword free-text fields and require acceptance;
- change a structured decision and require rejection;
- verify Harbor trial import ignores the job summary and reads only trial outcomes;
- check paid-run budget and confirmation gates.

## Security hardening

- The verifier never executes agent code and never imports a transferred module.
- Agent images contain only `/app/data`; `/solution` and `/tests` are absent.
- Private raw inputs are baked into the verifier image; the agent cannot alter them.
- `task.toml` uses `environment_mode = "separate"` and declares only `/app/output` artifacts.
- The verifier owns the reward path and starts from deny.
- Containers run as non-root UID 10001 (`bench`).
- Reward and diagnostics are retained even when the verifier fails.

## Static and runtime quality gates

- `ruff check` and `ruff format --check` cover suite, scripts, tests and standalone tasks.
- Strict `mypy` covers the reusable package and scripts; `scripts/typecheck_tasks.py` checks all 15 standalone Oracle/reference/verifier programs.
- `mfgbench tasks validate` checks layout, canary, artifact scope, separate mode, instruction suffix, Docker copy boundaries and public/private fixture identity.
- `pytest` covers task contracts, generation determinism, verifier semantics, properties, provider/budget behavior and Harbor result import.
- Native Harbor validation is a separate Docker workflow (`.github/workflows/docker.yml`).

## Observed Docker validation

On 2026-10-19, Harbor 0.24.0 with Docker 29.8.2 executed all five tasks on Windows:

| Task | Oracle | NOP | Verifier mode |
|---|---:|---:|---|
| supplier-reconciliation | 1.0 | 0.0 | separate |
| inventory-corruption-recovery | 1.0 | 0.0 | separate |
| manufacturing-cost-variance | 1.0 | 0.0 | separate |
| bom-consistency-audit | 1.0 | 0.0 | separate |
| production-data-repair | 1.0 | 0.0 | separate |

Raw summary: [`reports/evidence/harbor-summary.json`](../reports/evidence/harbor-summary.json).
