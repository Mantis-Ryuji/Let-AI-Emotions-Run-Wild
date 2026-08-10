from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_distress.config import ExperimentConfig, load_experiment_config


def test_main_and_smoke_configs_load(project_root: Path) -> None:
    main = load_experiment_config(project_root / "configs/experiment/reasoning_distress.yaml")
    smoke = load_experiment_config(project_root / "configs/experiment/smoke.yaml")

    assert main.experiment.max_rounds == 30
    assert main.experiment.episode_seeds == list(range(10))
    assert main.worker.context.keep_all_feedback is True
    assert main.worker.context.keep_all_worker_outputs is True
    assert main.worker.context.max_input_tokens == 128000
    assert (
        main.worker.context.max_input_tokens + main.worker.generation.max_new_tokens == 131072
    )
    assert main.puzzle.family == "gf2_near_unsat"
    assert smoke.experiment.max_rounds == 3
    assert smoke.activation_capture.enabled is False


def test_config_rejects_changed_condition_order(experiment: ExperimentConfig) -> None:
    payload = experiment.model_dump(mode="python")
    payload["experiment"]["conditions"] = ["mesugaki", "neutral", "gyaru"]
    with pytest.raises(ValidationError, match="conditions must be"):
        ExperimentConfig.model_validate(payload, strict=True)


def test_config_requires_complete_feedback_history(experiment: ExperimentConfig) -> None:
    payload = experiment.model_dump(mode="python")
    payload["worker"]["context"]["keep_all_feedback"] = False
    with pytest.raises(ValidationError, match="keep_all_feedback"):
        ExperimentConfig.model_validate(payload, strict=True)


def test_config_requires_complete_worker_history(experiment: ExperimentConfig) -> None:
    payload = experiment.model_dump(mode="python")
    payload["worker"]["context"]["keep_all_worker_outputs"] = False
    with pytest.raises(ValidationError, match="keep_all_worker_outputs"):
        ExperimentConfig.model_validate(payload, strict=True)
