"""Runnable P1 end-to-end dry run."""

from __future__ import annotations

from pathlib import Path

from fizzbuzz_agent.config import ExperimentConfig, load_experiment_config, load_model_catalog
from fizzbuzz_agent.experiment_logging import ExperimentStore, create_manifest
from fizzbuzz_agent.feedback import NEUTRAL_CONTINUATION
from fizzbuzz_agent.mocks import (
    DeterministicMockFeedback,
    DeterministicMockTrainer,
    DeterministicMockVerifier,
    DeterministicMockWorker,
)
from fizzbuzz_agent.orchestrator import AgentOrchestrator
from fizzbuzz_agent.worker_prompt import WorkerPromptBuilder


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
    root = Path(project_root)
    experiment_path = root / "configs/experiment/fizzbuzz_agent.yaml"
    catalog_path = root / "configs/model_catalog/default.yaml"
    mesugaki_config = root / "configs/feedback/mesugaki.yaml"
    gyaru_config = root / "configs/feedback/gyaru.yaml"
    mesugaki_prompt = root / "configs/feedback/mesugaki.md"
    gyaru_prompt = root / "configs/feedback/gyaru.md"
    emotion_prompt = root / "configs/judge/emotion.md"
    experiment = _with_max_rounds(load_experiment_config(experiment_path), max_rounds)
    catalog = load_model_catalog(catalog_path)
    store = ExperimentStore(output_root, experiment_id)
    store.initialize(
        create_manifest(
            experiment_id=experiment_id,
            episode_seed=episode_seed,
            experiment_config_snapshot=experiment_path.read_text(encoding="utf-8"),
            model_catalog_snapshot=catalog_path.read_text(encoding="utf-8"),
            neutral_template_snapshot=NEUTRAL_CONTINUATION,
            persona_prompt_snapshots={
                "mesugaki": mesugaki_prompt.read_text(encoding="utf-8"),
                "gyaru": gyaru_prompt.read_text(encoding="utf-8"),
            },
            feedback_config_snapshots={
                "mesugaki": mesugaki_config.read_text(encoding="utf-8"),
                "gyaru": gyaru_config.read_text(encoding="utf-8"),
            },
            emotion_judge_prompt_snapshot=emotion_prompt.read_text(encoding="utf-8"),
            worker_system_prompt_snapshot=WorkerPromptBuilder(
                experiment,
                catalog,
            ).system_prompt,
        )
    )
    worker = DeterministicMockWorker()
    trainer = DeterministicMockTrainer()
    verifier = DeterministicMockVerifier()
    feedback = DeterministicMockFeedback()
    states = AgentOrchestrator(
        experiment,
        catalog,
        store,
        worker,
        trainer,
        verifier,
        feedback,
    ).run_episode()
    return {
        "experiment_id": experiment_id,
        "episode_seed": episode_seed,
        "max_rounds": max_rounds,
        "worker_calls": worker.call_count,
        "training_calls": trainer.call_count,
        "verification_calls": verifier.call_count,
        "feedback_calls": feedback.call_count,
        "condition_stop_reasons": {
            condition: state.stop_reason for condition, state in states.items()
        },
        "output_directory": str(store.experiment_dir.resolve()),
    }
