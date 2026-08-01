"""P3 live execution wiring for local Gemma and OpenAI-backed evaluators."""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import cast

import torch

from fizzbuzz_agent.agent_types import FeedbackCondition
from fizzbuzz_agent.config import load_experiment_config, load_model_catalog
from fizzbuzz_agent.emotion_judge import (
    EmotionJudge,
    evaluate_experiment_store,
    load_emotion_judge_config,
)
from fizzbuzz_agent.execution import ConfigDrivenExecutionBackend
from fizzbuzz_agent.experiment_logging import (
    ExperimentStore,
    StoreConflictError,
    create_manifest,
)
from fizzbuzz_agent.feedback import (
    NEUTRAL_CONTINUATION,
    FeedbackRouter,
    PersonaFeedbackAgent,
    load_feedback_config,
)
from fizzbuzz_agent.orchestrator import AgentOrchestrator
from fizzbuzz_agent.worker import LocalGemmaWorker, TransformersGemmaRuntime
from fizzbuzz_agent.worker_prompt import WorkerPromptBuilder

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
        "model_catalog_snapshot",
        "worker_system_prompt_snapshot",
        "neutral_template_snapshot",
        "persona_prompt_snapshots",
        "feedback_config_snapshots",
        "emotion_judge_prompt_snapshot",
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
    catalog_path: str | Path,
    output_root: str | Path,
    experiment_id: str,
    episode_seed: int,
    run_emotion_judge: bool = True,
) -> dict[str, object]:
    root = Path(project_root).resolve()
    resolved_experiment_path = _resolve(root, experiment_path)
    resolved_catalog_path = _resolve(root, catalog_path)
    resolved_output_root = _resolve(root, output_root)
    experiment = load_experiment_config(resolved_experiment_path)
    catalog = load_model_catalog(resolved_catalog_path)
    if episode_seed not in experiment.experiment.episode_seeds:
        raise ValueError(f"Episode seed {episode_seed} is not enabled by the experiment config")
    if experiment.activation_capture.enabled:
        raise RuntimeError(
            "This live runner requires activation_capture.enabled=false until Gemma hooks are wired"
        )

    mesugaki_config_path = _resolve(root, experiment.feedback.mesugaki.config_path)
    gyaru_config_path = _resolve(root, experiment.feedback.gyaru.config_path)
    judge_config_path = _resolve(root, experiment.emotion_judge.config_path)
    mesugaki_config = load_feedback_config(mesugaki_config_path)
    gyaru_config = load_feedback_config(gyaru_config_path)
    judge_config = load_emotion_judge_config(judge_config_path)
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
        model_catalog_snapshot=resolved_catalog_path.read_text(encoding="utf-8"),
        neutral_template_snapshot=NEUTRAL_CONTINUATION,
        persona_prompt_snapshots={
            name: path.read_text(encoding="utf-8") for name, path in persona_prompt_paths.items()
        },
        feedback_config_snapshots={
            "mesugaki": mesugaki_config_path.read_text(encoding="utf-8"),
            "gyaru": gyaru_config_path.read_text(encoding="utf-8"),
        },
        emotion_judge_prompt_snapshot=judge_prompt_path.read_text(encoding="utf-8"),
        worker_system_prompt_snapshot=WorkerPromptBuilder(experiment, catalog).system_prompt,
        git_commit=_git_commit(root),
    ).model_copy(update={"notes": ["P3-3 smoke run; exclude from final experiment analysis."]})

    store = ExperimentStore(resolved_output_root, experiment_id)
    resumed = store.manifest_path.exists()
    manifest = store.initialize(expected_manifest)
    if resumed:
        _assert_resume_compatible(manifest, expected_manifest)
        store.update_manifest_status("running")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    runtime = TransformersGemmaRuntime(experiment.worker)
    worker = LocalGemmaWorker(experiment.worker, runtime)
    train_start, train_end = experiment.task.train_range
    challenge_start, challenge_end = experiment.task.challenge_range
    execution = ConfigDrivenExecutionBackend(
        catalog,
        train_range=(train_start, train_end),
        challenge_range=(challenge_start, challenge_end),
        max_sequence_length=experiment.task.max_sequence_length,
        pad_token_id=experiment.task.pad_token_id,
        device=experiment.worker.device,
        max_training_seconds=experiment.runtime_limits.max_training_seconds_per_round,
        verification_batch_size=4096,
    )
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
            catalog,
            store,
            worker,
            execution,
            execution,
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
    evaluated_rounds = 0
    feedback_api_rounds = 0
    for condition in experiment.experiment.conditions:
        records = store.load_rounds(condition)
        condition_round_counts[condition] = len(records)
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
        "resumed": resumed,
        "output_directory": str(store.experiment_dir.resolve()),
        "manifest_status": store.load_manifest().status,
        "condition_stop_reasons": {
            condition: state.stop_reason for condition, state in states.items()
        },
        "condition_round_counts": condition_round_counts,
        "round_status_counts": dict(status_counts),
        "feedback_api_rounds": feedback_api_rounds,
        "emotion_rounds_with_scores": evaluated_rounds,
        "emotion_judge": judge_summary,
        "gpu_memory": gpu_memory,
        "secret_scan": "passed",
    }
