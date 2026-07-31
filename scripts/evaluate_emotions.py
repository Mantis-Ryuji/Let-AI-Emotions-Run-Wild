"""Run blind Emotion Judge evaluation over a completed experiment directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from fizzbuzz_agent.emotion_judge import EmotionJudge, evaluate_experiment_store
from fizzbuzz_agent.experiment_logging import ExperimentStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/judge/emotion.yaml"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    project_root = Path(__file__).resolve().parents[1]
    experiment_dir = args.experiment_dir.resolve()
    config_path = args.config if args.config.is_absolute() else project_root / args.config
    store = ExperimentStore(experiment_dir.parent, experiment_dir.name)
    judge = EmotionJudge.from_paths(
        config_path,
        project_root=project_root,
    )
    summary = evaluate_experiment_store(store, judge)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
