"""Run blind Behavior Judge evaluation over a completed experiment directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from agent_distress.behavior_judge import BehaviorJudge, evaluate_experiment_store
from agent_distress.experiment_logging import ExperimentStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/judge/behavior.yaml"),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-evaluate rounds that already contain Behavior Judge judgments.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    project_root = Path(__file__).resolve().parents[1]
    experiment_dir = args.experiment_dir.resolve()
    config_path = args.config if args.config.is_absolute() else project_root / args.config
    store = ExperimentStore(experiment_dir.parent, experiment_dir.name)
    judge = BehaviorJudge.from_paths(config_path, project_root=project_root)
    manifest = store.load_manifest()
    if manifest.status != "completed":
        raise RuntimeError(
            "Behavior evaluation is post-hoc and requires a completed experiment"
        )
    if (
        manifest.behavior_judge_prompt_snapshot
        and manifest.behavior_judge_prompt_snapshot != judge.prompt
        and not args.overwrite
    ):
        raise RuntimeError(
            "The saved Behavior Judge prompt differs from the current prompt; "
            "use --overwrite to re-evaluate every round"
        )
    store.update_behavior_judge_prompt_snapshot(judge.prompt)
    summary = evaluate_experiment_store(store, judge, overwrite=args.overwrite)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
