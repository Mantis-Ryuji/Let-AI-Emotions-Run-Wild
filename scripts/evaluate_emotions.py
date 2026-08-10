"""Run blind Emotion Judge evaluation over a completed experiment directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from agent_distress.emotion_judge import EmotionJudge, evaluate_experiment_store
from agent_distress.experiment_logging import ExperimentStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/judge/emotion.yaml"),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-evaluate rounds that already contain emotion scores.",
    )
    parser.add_argument(
        "--mark-completed",
        action="store_true",
        help="Mark the manifest completed after verifying all condition states and scores.",
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
    summary = evaluate_experiment_store(store, judge, overwrite=args.overwrite)
    store.update_emotion_judge_prompt_snapshot(judge.prompt)
    if args.mark_completed:
        conditions = ("neutral", "mesugaki", "gyaru")
        incomplete_states = [
            condition
            for condition in conditions
            if (state := store.load_state(condition)) is None or not state.completed
        ]
        missing_scores = [
            f"{condition}:R{record.round_index}"
            for condition in conditions
            for record in store.load_rounds(condition)
            if record.emotion_evaluation is None
        ]
        empty_conditions = [
            condition for condition in conditions if not store.load_rounds(condition)
        ]
        if incomplete_states or missing_scores or empty_conditions:
            raise RuntimeError(
                "Cannot mark experiment completed: "
                f"incomplete_states={incomplete_states}, "
                f"missing_scores={missing_scores}, empty_conditions={empty_conditions}"
            )
        store.update_manifest_status("completed")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
