# Terminal-Bench-Style Manufacturing Challenge Suite

A Terminal-Bench-style suite of manufacturing reconciliation and data-repair challenges.

## Features

- Five manufacturing benchmark tasks covering reconciliation, inventory recovery, cost variance, BOM audit, and production data repair.
- Terminal-Bench-style task definitions with clear instructions and deterministic data.
- Independent verifiers and held-out checks for each challenge.
- Reported expected outcomes and evidence for review.
- Reusable task layout for running agents in isolated terminals.
- Manufacturing-focused datasets with realistic edge cases.

## Stack

Python

## Clone

```bash
git clone https://github.com/sanjaymouraly/terminal-bench-manufacturing-suite.git
cd terminal-bench-manufacturing-suite
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Run

```bash
python -m compileall -q src tests scripts tasks
mfgbench --help
```

## Tests

```bash
pytest -q
```

## Notes

- Sample data, when included, is synthetic.

## License

MIT © 2025 [Sanjay Mouraly](https://github.com/sanjaymouraly)
