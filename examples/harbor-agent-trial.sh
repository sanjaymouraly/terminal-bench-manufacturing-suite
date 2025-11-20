#!/bin/sh
# Print — never execute — a budgeted Harbor agent-trial starter.
# Requires an installed/running Docker daemon, Harbor, and locally configured credentials.
set -eu

TASK="${1:-supplier-reconciliation}"
MODEL="${2:-}"
PROVIDER="${3:-}"
if [ -z "$MODEL" ] || [ -z "$PROVIDER" ]; then
  echo "Usage: $0 <task-slug> <provider/model> <provider-name>" >&2
  echo "Example: $0 supplier-reconciliation anthropic/<model> anthropic" >&2
  exit 2
fi

cat <<EOF
No evaluation has been launched. Review the task, add real dated rates to your ignored
provider config, replace token numbers and USD cap below with an approved budget, then
run the command yourself:

mfgbench harbor-run "$TASK" \\
  --agent claude-code --model "$MODEL" --provider "$PROVIDER" \\
  --attempts 1 --max-agent-timeout-seconds 900 --max-turns 12 \\
  --planned-input-tokens 250000 --planned-output-tokens 75000 \\
  --max-input-tokens 250000 --max-output-tokens 75000 --max-estimated-usd 10 \\
  --execute --confirm-paid

The wrapper rejects a paid launch if configuration, dated pricing, plan, cap, or explicit
confirmation is absent. After an actual run, inspect its Harbor job directory and analyze
observed trajectories; do not publish a claimed result without the resulting evidence.
EOF
