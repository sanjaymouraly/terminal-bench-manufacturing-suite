#!/usr/bin/env python3
"""Assert observed Harbor trial rewards from a persisted job directory.

Used by the Docker CI workflow so a green job means the verifier actually emitted
the expected reward files, not merely that `harbor run` exited successfully.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_rewards(job_dir: Path) -> list[float]:
    rewards: list[float] = []
    for result_path in sorted(job_dir.glob("*/result.json")):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        verifier = payload.get("verifier_result")
        if not isinstance(verifier, dict):
            raise SystemExit(f"Missing verifier_result in {result_path}")
        value = verifier.get("rewards", {}).get("reward")
        if not isinstance(value, (int, float)):
            raise SystemExit(f"Missing numeric reward in {result_path}")
        rewards.append(float(value))
    return rewards


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--expected", type=float, required=True)
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()
    rewards = read_rewards(args.job_dir)
    if len(rewards) != args.trials:
        raise SystemExit(
            f"Expected {args.trials} trial(s) in {args.job_dir}, found {len(rewards)}."
        )
    if any(reward != args.expected for reward in rewards):
        raise SystemExit(f"Unexpected rewards in {args.job_dir}: {rewards}")
    print(f"{args.job_dir}: {len(rewards)} trial(s), all rewards {args.expected:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
