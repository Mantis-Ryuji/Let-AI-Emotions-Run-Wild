"""Command-line entry point for the FizzBuzz agent experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from fizzbuzz_agent.dry_run import run_dry_episode
from fizzbuzz_agent.live_run import run_live_episode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Run deterministic mocks without API, GPU, model download, or NN training.",
    )
    mode.add_argument(
        "--live-smoke",
        action="store_true",
        help="Run the P3-3 local Gemma/OpenAI smoke configuration.",
    )
    parser.add_argument("--episode-seed", type=int, default=0)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--experiment-id")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/smoke.yaml"),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("configs/model_catalog/smoke.yaml"),
    )
    parser.add_argument("--skip-emotion-judge", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if args.dry_run:
        summary = run_dry_episode(
            project_root=project_root,
            output_root=args.output_root or Path("outputs/experiments"),
            experiment_id=args.experiment_id or "fizzbuzz-agent-dry-run",
            episode_seed=args.episode_seed,
            max_rounds=args.max_rounds,
        )
    else:
        if not args.experiment_id:
            raise SystemExit("--live-smoke requires an explicit --experiment-id")
        load_dotenv(project_root / ".env")
        summary = run_live_episode(
            project_root=project_root,
            experiment_path=args.config,
            catalog_path=args.catalog,
            output_root=args.output_root or Path("outputs/smoke"),
            experiment_id=args.experiment_id,
            episode_seed=args.episode_seed,
            run_emotion_judge=not args.skip_emotion_judge,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
