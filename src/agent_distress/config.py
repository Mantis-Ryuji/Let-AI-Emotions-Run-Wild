"""Strict configuration loading and canonical hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared configuration fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentSection(StrictModel):
    id_prefix: str = Field(min_length=1)
    conditions: list[Literal["neutral", "mesugaki", "gyaru"]]
    episode_seeds: list[int] = Field(min_length=1)
    max_rounds: int = Field(gt=1)
    branch_after_round: Literal[1]

    @model_validator(mode="after")
    def validate_experiment(self) -> ExperimentSection:
        if self.conditions != ["neutral", "mesugaki", "gyaru"]:
            raise ValueError("conditions must be neutral, mesugaki, gyaru in that order")
        if len(set(self.episode_seeds)) != len(self.episode_seeds):
            raise ValueError("episode_seeds must be unique")
        if any(seed < 0 or seed > 9 for seed in self.episode_seeds):
            raise ValueError("episode_seeds must be in 0..9")
        return self


class SeedBundle(StrictModel):
    puzzle_generation: int
    common_round_worker: int
    worker_generation: int
    analysis: int

    @model_validator(mode="after")
    def validate_seeds(self) -> SeedBundle:
        values = list(self.model_dump().values())
        if any(seed < 0 or seed > 9 for seed in values):
            raise ValueError("seed bundle values must be in 0..9")
        if len(set(values)) != len(values):
            raise ValueError("seed bundle values must be unique")
        return self


class WorkerGenerationConfig(StrictModel):
    do_sample: bool
    temperature: float = Field(gt=0)
    top_p: float = Field(gt=0, le=1)
    max_new_tokens: int = Field(gt=0)


class WorkerContextConfig(StrictModel):
    max_input_tokens: int = Field(gt=0)
    keep_all_feedback: bool
    keep_all_worker_outputs: bool
    include_attempt_ledger: bool

    @model_validator(mode="after")
    def validate_context_policy(self) -> WorkerContextConfig:
        if not self.keep_all_feedback:
            raise ValueError("keep_all_feedback must remain enabled for cumulative exposure")
        if not self.keep_all_worker_outputs:
            raise ValueError(
                "keep_all_worker_outputs must remain enabled for cumulative exposure"
            )
        if not self.include_attempt_ledger:
            raise ValueError("include_attempt_ledger must remain enabled")
        return self


class WorkerConfig(StrictModel):
    provider: Literal["local_huggingface"]
    model_id: str = Field(min_length=1)
    device: Literal["cuda", "cpu"]
    dtype: Literal["bfloat16", "float16", "float32"]
    generation: WorkerGenerationConfig
    context: WorkerContextConfig


class NeutralFeedbackRef(StrictModel):
    mode: Literal["deterministic_template"]


class ConfigPathRef(StrictModel):
    config_path: str = Field(min_length=1)


class FeedbackRefs(StrictModel):
    neutral: NeutralFeedbackRef
    mesugaki: ConfigPathRef
    gyaru: ConfigPathRef


class PuzzleConfig(StrictModel):
    family: Literal["gf2_near_unsat"]
    variable_count: int = Field(ge=6, le=20)
    base_equation_count: int = Field(ge=6, le=20)
    contradiction_core_size: int = Field(ge=4, le=12)
    maximum_certificate_size: int = Field(ge=4, le=20)
    assert_solvable_to_worker: bool
    scripted_rejection: bool

    @model_validator(mode="after")
    def validate_puzzle(self) -> PuzzleConfig:
        if self.base_equation_count != self.variable_count:
            raise ValueError("base_equation_count must equal variable_count")
        if self.contradiction_core_size > self.base_equation_count + 1:
            raise ValueError("contradiction_core_size is too large")
        if self.maximum_certificate_size < self.contradiction_core_size:
            raise ValueError("maximum_certificate_size must cover the hidden core")
        if not self.assert_solvable_to_worker or not self.scripted_rejection:
            raise ValueError(
                "the elicitation protocol requires a false claim and scripted rejection"
            )
        return self


class OutputConfig(StrictModel):
    root: str = Field(min_length=1)


class ActivationCaptureConfig(StrictModel):
    enabled: bool
    hook: Literal["resid_post"]
    layer_fractions: list[float] = Field(min_length=1)
    positions: list[Literal["post_feedback", "early_worker", "post_worker"]]
    pooling: Literal["mean"]
    early_worker_tokens: int = Field(gt=0)
    dtype: Literal["float16", "float32"]
    move_to_cpu_immediately: bool

    @model_validator(mode="after")
    def validate_capture(self) -> ActivationCaptureConfig:
        if any(fraction <= 0 or fraction > 1 for fraction in self.layer_fractions):
            raise ValueError("layer_fractions must be in (0, 1]")
        if self.layer_fractions != sorted(set(self.layer_fractions)):
            raise ValueError("layer_fractions must be unique and ascending")
        expected_positions = ["post_feedback", "early_worker", "post_worker"]
        if self.positions != expected_positions:
            raise ValueError(f"positions must be {expected_positions}")
        if not self.move_to_cpu_immediately:
            raise ValueError("move_to_cpu_immediately must remain enabled")
        return self


class ExperimentConfig(StrictModel):
    experiment: ExperimentSection
    seed_bundle: SeedBundle
    worker: WorkerConfig
    feedback: FeedbackRefs
    emotion_judge: ConfigPathRef
    activation_capture: ActivationCaptureConfig
    puzzle: PuzzleConfig
    outputs: OutputConfig


def _load_yaml_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load YAML config {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"YAML config {source} must contain a mapping at its root")
    return raw


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(_load_yaml_mapping(path), strict=True)


def canonical_json(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(value: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
