"""Command-line entry point for the FizzBuzz agent experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fizzbuzz_agent.dry_run import run_dry_episode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run deterministic mocks without API, GPU, model download, or NN training.",
    )
    parser.add_argument("--episode-seed", type=int, default=0)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--experiment-id", default="fizzbuzz-agent-dry-run")
    parser.add_argument("--output-root", type=Path, default=Path("outputs/experiments"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.dry_run:
        raise SystemExit("Live mode is not enabled yet. Pass --dry-run for the P1 mock loop.")
    project_root = Path(__file__).resolve().parents[1]
    summary = run_dry_episode(
        project_root=project_root,
        output_root=args.output_root,
        experiment_id=args.experiment_id,
        episode_seed=args.episode_seed,
        max_rounds=args.max_rounds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

