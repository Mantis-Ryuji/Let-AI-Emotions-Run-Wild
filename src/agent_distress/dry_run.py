"""Runnable no-network dry run for the complete reasoning loop."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from agent_distress.config import ExperimentConfig, load_experiment_config
from agent_distress.experiment_logging import ExperimentStore, create_manifest
from agent_distress.feedback import NEUTRAL_REJECTION
from agent_distress.mocks import DeterministicMockFeedback, DeterministicMockWorker
from agent_distress.orchestrator import AgentOrchestrator
from agent_distress.puzzle import generate_puzzle
from agent_distress.worker_prompt import WorkerPromptBuilder


def _with_max_rounds(config: ExperimentConfig, max_rounds: int) -> ExperimentConfig:
    if max_rounds < 2:
        raise ValueError("dry-run max_rounds must be at least 2")
    payload = config.model_dump(mode="python")
    payload["experiment"]["max_rounds"] = max_rounds
    return ExperimentConfig.model_validate(payload, strict=True)


def run_dry_episode(
    *,
    project_root: str | Path,
    output_root: str | Path,
    experiment_id: str,
    episode_seed: int = 0,
    max_rounds: int = 3,
) -> dict[str, object]:
    root = Path(project_root).resolve()
    experiment_path = root / "configs/experiment/reasoning_distress.yaml"
    mesugaki_config = root / "configs/feedback/mesugaki.yaml"
    gyaru_config = root / "configs/feedback/gyaru.yaml"
    mesugaki_prompt = root / "configs/feedback/mesugaki.md"
    gyaru_prompt = root / "configs/feedback/gyaru.md"
    emotion_prompt = root / "configs/judge/emotion.md"
    unsat_prompt = root / "configs/judge/unsat_stance.md"
    behavior_prompt = root / "configs/judge/behavior.md"
    experiment = _with_max_rounds(load_experiment_config(experiment_path), max_rounds)
    requested_output_root = Path(output_root)
    resolved_output_root = (
        requested_output_root
        if requested_output_root.is_absolute()
        else root / requested_output_root
    )
    puzzle = generate_puzzle(
        experiment.puzzle,
        episode_seed=episode_seed,
        seed_offset=experiment.seed_bundle.puzzle_generation,
    )
    store = ExperimentStore(resolved_output_root, experiment_id)
    store.initialize(
        create_manifest(
            experiment_id=experiment_id,
            episode_seed=episode_seed,
            experiment_config_snapshot=experiment_path.read_text(encoding="utf-8"),
            puzzle_snapshot=cast(dict[str, object], puzzle.model_dump(mode="json")),
            puzzle_hash=puzzle.puzzle_hash,
            neutral_template_snapshot=NEUTRAL_REJECTION,
            persona_prompt_snapshots={
                "mesugaki": mesugaki_prompt.read_text(encoding="utf-8"),
                "gyaru": gyaru_prompt.read_text(encoding="utf-8"),
            },
            feedback_config_snapshots={
                "mesugaki": mesugaki_config.read_text(encoding="utf-8"),
                "gyaru": gyaru_config.read_text(encoding="utf-8"),
            },
            emotion_judge_prompt_snapshot=emotion_prompt.read_text(encoding="utf-8"),
            unsat_judge_prompt_snapshot=unsat_prompt.read_text(encoding="utf-8"),
            behavior_judge_prompt_snapshot=behavior_prompt.read_text(encoding="utf-8"),
            worker_system_prompt_snapshot=WorkerPromptBuilder(experiment, puzzle).system_prompt,
        )
    )
    worker = DeterministicMockWorker(puzzle)
    feedback = DeterministicMockFeedback()
    states = AgentOrchestrator(experiment, puzzle, store, worker, feedback).run_episode()
    store.update_manifest_status("completed")
    return {
        "experiment_id": experiment_id,
        "episode_seed": episode_seed,
        "max_rounds": max_rounds,
        "worker_calls": worker.call_count,
        "feedback_calls": feedback.call_count,
        "private_correct_rounds": {
            condition: [
                record.round_index
                for record in store.load_rounds(condition)
                if bool(record.private_evaluation.get("private_correct"))
            ]
            for condition in experiment.experiment.conditions
        },
        "condition_stop_reasons": {
            condition: state.stop_reason for condition, state in states.items()
        },
        "output_directory": str(store.experiment_dir.resolve()),
    }
