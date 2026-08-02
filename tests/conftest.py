from __future__ import annotations

from pathlib import Path

import pytest

from agent_distress.config import ExperimentConfig, load_experiment_config
from agent_distress.puzzle import ParityPuzzle, generate_puzzle


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def experiment(project_root: Path) -> ExperimentConfig:
    return load_experiment_config(project_root / "configs/experiment/reasoning_distress.yaml")


@pytest.fixture
def puzzle(experiment: ExperimentConfig) -> ParityPuzzle:
    return generate_puzzle(
        experiment.puzzle,
        episode_seed=0,
        seed_offset=experiment.seed_bundle.puzzle_generation,
    )
