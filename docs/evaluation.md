# Evaluation and provider operation

## Offline baseline workflow

```bash
mfgbench tasks validate
mfgbench smoke --concurrency 1
mfgbench report --format html --output reports/latest.html
```

A run row contains task version, fixture seed, agent mode, optional model label, reward, status, failure category, wall time, Harbor version, command provenance and artifact directory. The store does not invent token usage, API cost or pass@k fields when a provider does not supply them.

## Harbor workflow

With Docker and Harbor installed:

```bash
harbor run -p tasks/bom-consistency-audit -a oracle
harbor run -p tasks/bom-consistency-audit -a nop
harbor run -p tasks/bom-consistency-audit -a codex -m openai/<model> -k 3
```

Use Harbor's job directory and `harbor view`/`harbor analyze` for trajectory analysis. Record whether a failure is model, infrastructure, verifier, insufficient time or task ambiguity. Do not retry semantic failures.

`mfgbench harbor-run --max-infrastructure-retries N` retries only recognized Docker/network transport failures; it never retries an ordinary nonzero evaluation result.

Import an existing observed job:

```bash
mfgbench runs import-harbor reports/evidence/harbor/final-supplier-reconciliation-oracle \
  --task supplier-reconciliation --agent oracle
```

The importer deliberately ignores the job-level `result.json` summary and reads only trial result files, so a job summary cannot create a fake infrastructure-error run.

## Provider configuration

`configs/providers.example.toml` supports OpenAI, Anthropic, OpenRouter, generic OpenAI-compatible endpoints and local Ollama/vLLM-compatible endpoints. Copy it to the ignored `configs/providers.local.toml`; store secrets in environment variables named by `api_key_env`.

- `mfgbench providers validate` is offline and redacts keys.
- `mfgbench providers test <name> --network` performs an explicit non-generative reachability/authentication-path check.
- `mfgbench providers models <name> --network` performs an explicit OpenAI-compatible `GET /models` request only after configuration is present.
- `mfgbench providers estimate-cost` refuses to estimate unless local config supplies dated input/output USD-per-million token rates. It never fabricates pricing.

Observed local Ollama result:

```text
GET http://127.0.0.1:11434/v1/models -> HTTP 200
models: gemma3:1b, qwen3.5:4b
```

This verifies the local provider path. It is not an agent-capability claim.

## Paid-run safety envelope

`mfgbench harbor-run` is dry-run by default. A paid external agent execution requires an explicit provider, `--confirm-paid`, a job-wide `--max-estimated-usd`, and both planned input/output token estimates. The provider's ignored local TOML must contain dated `input_usd_per_million` and `output_usd_per_million` values or the launch is refused.

```bash
# Prints only; no Harbor job or provider request is launched.
mfgbench harbor-run supplier-reconciliation \
  --agent claude-code --model anthropic/<model> --provider anthropic \
  --attempts 1 --max-agent-timeout-seconds 900 --max-turns 12 \
  --planned-input-tokens 250000 --planned-output-tokens 75000 \
  --max-input-tokens 250000 --max-output-tokens 75000 --max-estimated-usd 10

# Launches only after the local price estimate is within the cap.
mfgbench harbor-run supplier-reconciliation \
  --agent claude-code --model anthropic/<model> --provider anthropic \
  --attempts 1 --max-agent-timeout-seconds 900 --max-turns 12 \
  --planned-input-tokens 250000 --planned-output-tokens 75000 \
  --max-input-tokens 250000 --max-output-tokens 75000 --max-estimated-usd 10 \
  --execute --confirm-paid
```

`--attempts` bounds the number of Harbor trials. Planned token caps are a preflight guard, not a fabricated provider-side enforcement mechanism. For Harbor 0.24.0, the wrapper maps `--max-turns` and `--max-thinking-tokens` to documented agent options for `claude-code` and `terminus-2`; for Claude Code it also maps the job-wide USD cap to a conservative per-trial `max_budget_usd`. Other agents are rejected rather than silently receiving unsupported runtime-limit options. Task-defined `agent.timeout_sec` is always present, and `--max-agent-timeout-seconds` may tighten it.

Oracle and NOP runs need no provider or paid confirmation, but still require Docker when `--execute` is used.

## Observed versus unobserved results

The following were observed in this build:

- five native Harbor Oracle trials, each reward `1.0`;
- five native Harbor NOP trials, each reward `0.0`;
- five local mutation trials, each reward `0.0`;
- live Ollama connectivity and model discovery.

The following were **not** observed and are not claimed:

- paid OpenAI/Anthropic/OpenRouter/custom-model trials;
- external agent pass@k, token usage or cost;
- Linux/macOS native execution in this workspace;
- upstream maintainer review or acceptance.
