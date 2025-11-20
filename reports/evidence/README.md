# Evidence index

- `harbor-summary.json` - the ten native Harbor 0.24.0 trial rewards (five Oracle 1.0, five NOP 0.0) with task, agent, timing and verifier mode.
- `harbor/` - retained Harbor job directories for those ten trials, including trial logs, verifier results and transferred Oracle artifacts.
- `final-validation.txt` - final observed toolchain, lint, type-check, test, lock and build outcomes.
- `smoke-summary.txt` - captured local `mfgbench smoke --concurrency 3` transcript.

Absolute local paths in captured logs were replaced with `<repo>`, `<tmp>` and `<home>` before publication. No API keys or credentials are present.

Some `job.log` files contain Harbor's `compose cp failed; retrying with engine cp` fallback messages. These are artifact-transfer retries; the trial `result.json` and `verifier/reward.txt` are the authoritative outcomes.
