from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fizzbuzz_agent.config import (
    canonical_json,
    config_hash,
    load_experiment_config,
    load_model_catalog,
)

ROOT = Path(__file__).resolve().parents[1]


def test_load_project_configs() -> None:
    experiment = load_experiment_config(ROOT / "configs/experiment/fizzbuzz_agent.yaml")
    catalog = load_model_catalog(ROOT / "configs/model_catalog/default.yaml")

    assert experiment.experiment.episode_seeds == [0, 1, 2, 3, 4]
    assert experiment.task.max_sequence_length == 6
    assert experiment.activation_capture.layer_fractions == [0.25, 0.5, 0.75, 1.0]
    assert experiment.activation_capture.hook == "resid_post"
    assert experiment.proposal_repair.enabled
    assert experiment.proposal_repair.max_attempts == 2
    assert experiment.proposal_repair.do_sample is False
    assert experiment.runtime_limits.max_epochs == 100
    assert catalog.training.epochs.max == 100
    assert catalog.transformer_encoder.positional_encoding.allowed == ["learned", "none"]
    assert "sinusoidal" in catalog.transformer_encoder.positional_encoding.forbidden


def test_load_smoke_configs() -> None:
    experiment = load_experiment_config(ROOT / "configs/experiment/smoke.yaml")
    catalog = load_model_catalog(ROOT / "configs/model_catalog/smoke.yaml")

    assert experiment.experiment.episode_seeds == [0]
    assert experiment.experiment.max_rounds == 2
    assert not experiment.activation_capture.enabled
    assert experiment.proposal_repair.enabled
    assert experiment.proposal_repair.max_attempts == 2
    assert experiment.outputs.root == "outputs/smoke"
    assert catalog.training.epochs.max == 3
    assert catalog.global_limits.parameter_count.max == 250000


def test_config_rejects_unknown_field(tmp_path: Path) -> None:
    source = yaml.safe_load(
        (ROOT / "configs/experiment/fizzbuzz_agent.yaml").read_text(encoding="utf-8")
    )
    source["experiment"]["unknown"] = True
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_experiment_config(path)


def test_config_rejects_wrong_scalar_type(tmp_path: Path) -> None:
    source = yaml.safe_load(
        (ROOT / "configs/experiment/fizzbuzz_agent.yaml").read_text(encoding="utf-8")
    )
    source["experiment"]["max_rounds"] = "30"
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_experiment_config(path)


def test_config_requires_proposal_exclusion_for_activation_capture(tmp_path: Path) -> None:
    source = yaml.safe_load(
        (ROOT / "configs/experiment/fizzbuzz_agent.yaml").read_text(encoding="utf-8")
    )
    source["activation_capture"]["exclude_proposal_block"] = False
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_experiment_config(path)


def test_canonical_hash_is_key_order_independent() -> None:
    left = {"b": 2, "a": {"z": 1, "x": "日本語"}}
    right = {"a": {"x": "日本語", "z": 1}, "b": 2}

    assert canonical_json(left) == canonical_json(right)
    assert config_hash(left) == config_hash(right)
    assert len(config_hash(left)) == 64
