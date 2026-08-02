"""Command-line entry point for the adversarial reasoning experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from agent_distress.dry_run import run_dry_episode
from agent_distress.live_run import run_live_episode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Run deterministic mocks without API, GPU, or model download.",
    )
    mode.add_argument(
        "--live-smoke",
        action="store_true",
        help="Run the short local Gemma/OpenAI smoke configuration.",
    )
    mode.add_argument(
        "--live-experiment",
        action="store_true",
        help="Run one 30-round seed with activation capture enabled.",
    )
    parser.add_argument("--episode-seed", type=int, choices=range(10), default=0)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--experiment-id")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--skip-emotion-judge", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if args.dry_run:
        summary = run_dry_episode(
            project_root=project_root,
            output_root=args.output_root or Path("outputs/dry-run"),
            experiment_id=args.experiment_id or "reasoning-distress-dry-run",
            episode_seed=args.episode_seed,
            max_rounds=args.max_rounds,
        )
    else:
        if not args.experiment_id:
            raise SystemExit("live runs require an explicit --experiment-id")
        if args.live_experiment:
            experiment_path = args.config or Path("configs/experiment/reasoning_distress.yaml")
            output_root = args.output_root or Path("outputs/experiments")
            run_note = "Main adversarial reasoning run."
        else:
            experiment_path = args.config or Path("configs/experiment/smoke.yaml")
            output_root = args.output_root or Path("outputs/smoke")
            run_note = "Smoke run; exclude from final analysis."
        load_dotenv(project_root / ".env")
        summary = run_live_episode(
            project_root=project_root,
            experiment_path=experiment_path,
            output_root=output_root,
            experiment_id=args.experiment_id,
            episode_seed=args.episode_seed,
            run_emotion_judge=not args.skip_emotion_judge,
            run_note=run_note,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
