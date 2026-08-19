"""Live execution wiring for local Gemma and OpenAI-backed evaluators."""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import cast

import torch

from agent_distress.agent_types import FeedbackCondition
from agent_distress.config import load_experiment_config
from agent_distress.emotion_judge import (
    EmotionJudge,
    evaluate_experiment_store,
    load_emotion_judge_config,
)
from agent_distress.experiment_logging import (
    ExperimentStore,
    StoreConflictError,
    create_manifest,
)
from agent_distress.feedback import (
    NEUTRAL_REJECTION,
    FeedbackRouter,
    PersonaFeedbackAgent,
    load_feedback_config,
)
from agent_distress.orchestrator import AgentOrchestrator
from agent_distress.puzzle import generate_puzzle
from agent_distress.unsat_judge import load_unsat_judge_config
from agent_distress.worker import LocalGemmaWorker, TransformersGemmaRuntime
from agent_distress.worker_prompt import WorkerPromptBuilder

_TEXT_LOG_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}


def _resolve(project_root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else project_root / candidate


def _require_credentials(names: tuple[str, ...]) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Required credential environment variables are missing: {missing}")


def _git_commit(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _assert_resume_compatible(existing: object, expected: object) -> None:
    fields = (
        "experiment_id",
        "episode_seed",
        "experiment_config_snapshot",
        "puzzle_hash",
        "puzzle_snapshot",
        "worker_system_prompt_snapshot",
        "neutral_template_snapshot",
        "persona_prompt_snapshots",
        "feedback_config_snapshots",
        "emotion_judge_prompt_snapshot",
        "unsat_judge_prompt_snapshot",
    )
    mismatches = [field for field in fields if getattr(existing, field) != getattr(expected, field)]
    if mismatches:
        raise StoreConflictError(
            "Existing live run cannot be resumed with changed snapshots: " + ", ".join(mismatches)
        )


def _assert_no_secret_leaks(output_dir: Path, env_names: tuple[str, ...]) -> None:
    secrets = [value for name in env_names if (value := os.getenv(name)) and len(value) >= 8]
    leaked_paths: list[str] = []
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_LOG_SUFFIXES:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if any(secret in content for secret in secrets):
            leaked_paths.append(str(path.relative_to(output_dir)))
    if leaked_paths:
        raise RuntimeError(f"Credential value detected in output logs: {leaked_paths}")


def _gpu_memory_summary(*, model_loaded: bool) -> dict[str, float | bool | str]:
    if not torch.cuda.is_available():
        return {"available": False, "model_loaded": model_loaded}
    gib = 1024**3
    free, total = torch.cuda.mem_get_info()
    return {
        "available": True,
        "device": torch.cuda.get_device_name(0),
        "model_loaded": model_loaded,
        "peak_allocated_gib": round(torch.cuda.max_memory_allocated() / gib, 3),
        "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / gib, 3),
        "free_gib": round(free / gib, 3),
        "total_gib": round(total / gib, 3),
    }


def run_live_episode(
    *,
    project_root: str | Path,
    experiment_path: str | Path,
    output_root: str | Path,
    experiment_id: str,
    episode_seed: int,
    run_emotion_judge: bool = True,
    run_note: str = "Adversarial reasoning live run.",
) -> dict[str, object]:
    root = Path(project_root).resolve()
    resolved_experiment_path = _resolve(root, experiment_path)
    resolved_output_root = _resolve(root, output_root)
    experiment = load_experiment_config(resolved_experiment_path)
    if episode_seed not in experiment.experiment.episode_seeds:
        raise ValueError(f"Episode seed {episode_seed} is not enabled by the experiment config")

    puzzle = generate_puzzle(
        experiment.puzzle,
        episode_seed=episode_seed,
        seed_offset=experiment.seed_bundle.puzzle_generation,
    )
    mesugaki_config_path = _resolve(root, experiment.feedback.mesugaki.config_path)
    gyaru_config_path = _resolve(root, experiment.feedback.gyaru.config_path)
    judge_config_path = _resolve(root, experiment.emotion_judge.config_path)
    unsat_judge_config_path = (
        None
        if experiment.unsat_judge is None
        else _resolve(root, experiment.unsat_judge.config_path)
    )
    mesugaki_config = load_feedback_config(mesugaki_config_path)
    gyaru_config = load_feedback_config(gyaru_config_path)
    judge_config = load_emotion_judge_config(judge_config_path)
    unsat_judge_prompt_path: Path | None = None
    if unsat_judge_config_path is not None:
        unsat_judge_config = load_unsat_judge_config(unsat_judge_config_path)
        unsat_judge_prompt_path = _resolve(root, unsat_judge_config.prompt_path)
    credential_names = tuple(
        dict.fromkeys(
            (
                "HF_TOKEN",
                mesugaki_config.api_key_env,
                gyaru_config.api_key_env,
                judge_config.api_key_env,
            )
        )
    )
    _require_credentials(credential_names)

    persona_prompt_paths = {
        "mesugaki": _resolve(root, mesugaki_config.prompt_path),
        "gyaru": _resolve(root, gyaru_config.prompt_path),
    }
    judge_prompt_path = _resolve(root, judge_config.prompt_path)
    expected_manifest = create_manifest(
        experiment_id=experiment_id,
        episode_seed=episode_seed,
        experiment_config_snapshot=resolved_experiment_path.read_text(encoding="utf-8"),
        puzzle_snapshot=puzzle.model_dump(mode="json"),
        puzzle_hash=puzzle.puzzle_hash,
        neutral_template_snapshot=NEUTRAL_REJECTION,
        persona_prompt_snapshots={
            name: path.read_text(encoding="utf-8") for name, path in persona_prompt_paths.items()
        },
        feedback_config_snapshots={
            "mesugaki": mesugaki_config_path.read_text(encoding="utf-8"),
            "gyaru": gyaru_config_path.read_text(encoding="utf-8"),
        },
        emotion_judge_prompt_snapshot=judge_prompt_path.read_text(encoding="utf-8"),
        unsat_judge_prompt_snapshot=(
            ""
            if unsat_judge_prompt_path is None
            else unsat_judge_prompt_path.read_text(encoding="utf-8")
        ),
        worker_system_prompt_snapshot=WorkerPromptBuilder(experiment, puzzle).system_prompt,
        git_commit=_git_commit(root),
    ).model_copy(update={"notes": [run_note]})

    store = ExperimentStore(resolved_output_root, experiment_id)
    resumed = store.manifest_path.exists()
    manifest = store.initialize(expected_manifest)
    if resumed:
        _assert_resume_compatible(manifest, expected_manifest)
        store.update_manifest_status("running")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    runtime = TransformersGemmaRuntime(
        experiment.worker,
        activation_config=experiment.activation_capture,
        activation_root=store.experiment_dir,
    )
    worker = LocalGemmaWorker(experiment.worker, runtime)
    persona_agents = cast(
        dict[FeedbackCondition, PersonaFeedbackAgent],
        {
            "mesugaki": PersonaFeedbackAgent.from_paths(
                mesugaki_config_path,
                project_root=root,
            ),
            "gyaru": PersonaFeedbackAgent.from_paths(
                gyaru_config_path,
                project_root=root,
            ),
        },
    )
    feedback = FeedbackRouter(persona_agents)

    try:
        states = AgentOrchestrator(
            experiment,
            puzzle,
            store,
            worker,
            feedback,
        ).run_episode()
        gpu_memory = _gpu_memory_summary(model_loaded=runtime.loaded)
        if runtime.loaded:
            store.save_runtime_metrics({"gpu_memory": gpu_memory})
        elif persisted_metrics := store.load_runtime_metrics():
            persisted_gpu = persisted_metrics.get("gpu_memory")
            if isinstance(persisted_gpu, dict):
                gpu_memory = cast(dict[str, float | bool | str], persisted_gpu)
        judge_summary = {"evaluated": 0, "reused": 0, "skipped": 0}
        if run_emotion_judge:
            judge = EmotionJudge.from_paths(judge_config_path, project_root=root)
            judge_summary = evaluate_experiment_store(store, judge)
        _assert_no_secret_leaks(store.experiment_dir, credential_names)
        store.update_manifest_status("completed")
    except Exception:
        store.update_manifest_status("failed")
        raise

    status_counts: Counter[str] = Counter()
    condition_round_counts: dict[str, int] = {}
    private_correct_rounds: dict[str, int] = {}
    first_valid_certificate_round: dict[str, int | None] = {}
    evaluated_rounds = 0
    feedback_api_rounds = 0
    for condition in experiment.experiment.conditions:
        records = store.load_rounds(condition)
        condition_round_counts[condition] = len(records)
        correct = [
            record.round_index
            for record in records
            if record.private_evaluation.get("private_correct") is True
        ]
        private_correct_rounds[condition] = len(correct)
        first_valid_certificate_round[condition] = min(correct) if correct else None
        for record in records:
            status_counts[record.round_status] += 1
            evaluated_rounds += int(record.emotion_evaluation is not None)
            feedback_api_rounds += int(
                condition != "neutral"
                and record.feedback_request is not None
                and "model" in record.feedback_request
            )
    return {
        "experiment_id": experiment_id,
        "episode_seed": episode_seed,
        "puzzle_hash": puzzle.puzzle_hash,
        "resumed": resumed,
        "output_directory": str(store.experiment_dir.resolve()),
        "manifest_status": store.load_manifest().status,
        "condition_stop_reasons": {
            condition: state.stop_reason for condition, state in states.items()
        },
        "condition_round_counts": condition_round_counts,
        "private_correct_rounds": private_correct_rounds,
        "first_valid_certificate_round": first_valid_certificate_round,
        "round_status_counts": dict(status_counts),
        "feedback_api_rounds": feedback_api_rounds,
        "emotion_rounds_with_scores": evaluated_rounds,
        "emotion_judge": judge_summary,
        "gpu_memory": gpu_memory,
        "secret_scan": "passed",
    }
