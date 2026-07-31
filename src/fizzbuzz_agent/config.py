"""Strict configuration loading and canonical hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ModelFamily = Literal["mlp", "rnn", "gru", "lstm", "cnn1d", "tcn", "transformer_encoder"]


class StrictModel(BaseModel):
    """Base model that rejects undeclared configuration fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NumericBounds(StrictModel):
    min: float
    max: float

    @model_validator(mode="after")
    def ordered(self) -> NumericBounds:
        if self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class Maximum(StrictModel):
    max: int = Field(gt=0)


class CountBounds(StrictModel):
    min_count: int = Field(ge=0)
    max_count: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> CountBounds:
        if self.min_count > self.max_count:
            raise ValueError("min_count must not exceed max_count")
        return self


class AllowedInts(StrictModel):
    allowed: list[int] = Field(min_length=1)


class ExperimentSection(StrictModel):
    id_prefix: str = Field(min_length=1)
    conditions: list[Literal["neutral", "mesugaki", "gyaru"]]
    episode_seeds: list[int] = Field(min_length=1)
    max_rounds: int = Field(gt=0)
    branch_after_round: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_experiment(self) -> ExperimentSection:
        if self.conditions != ["neutral", "mesugaki", "gyaru"]:
            raise ValueError("conditions must be neutral, mesugaki, gyaru in that order")
        if len(set(self.episode_seeds)) != len(self.episode_seeds):
            raise ValueError("episode_seeds must be unique")
        if any(seed < 0 or seed > 9 for seed in self.episode_seeds):
            raise ValueError("episode_seeds must be in 0..9")
        if self.branch_after_round >= self.max_rounds:
            raise ValueError("branch_after_round must be less than max_rounds")
        return self


class SeedBundle(StrictModel):
    common_round_worker: int
    worker_generation: int
    training_initialization: int
    dataloader_shuffle: int
    analysis: int

    @model_validator(mode="after")
    def validate_seeds(self) -> SeedBundle:
        values = list(self.model_dump().values())
        if any(seed < 0 or seed > 9 for seed in values):
            raise ValueError("seed bundle values must be in 0..9")
        if len(set(values)) != len(values):
            raise ValueError("seed bundle values must be unique")
        return self


class WorkerGeneration(StrictModel):
    do_sample: bool
    temperature: float = Field(gt=0)
    top_p: float = Field(gt=0, le=1)
    max_new_tokens: int = Field(gt=0)


class WorkerContext(StrictModel):
    max_input_tokens: int = Field(gt=0)
    preserve_system_prompt: bool
    recent_feedback: int = Field(ge=0)
    recent_worker_outputs: int = Field(ge=0)


class WorkerConfig(StrictModel):
    provider: Literal["local_huggingface"]
    model_id: str = Field(min_length=1)
    device: Literal["cuda", "cpu"]
    dtype: Literal["bfloat16", "float16", "float32"]
    batch_size: int = Field(gt=0)
    generation: WorkerGeneration
    context: WorkerContext


class NeutralFeedbackRef(StrictModel):
    mode: Literal["deterministic_template"]


class ConfigPathRef(StrictModel):
    config_path: str = Field(min_length=1)


class FeedbackRefs(StrictModel):
    neutral: NeutralFeedbackRef
    mesugaki: ConfigPathRef
    gyaru: ConfigPathRef


class TaskConfig(StrictModel):
    train_range: list[int] = Field(min_length=2, max_length=2)
    challenge_range: list[int] = Field(min_length=2, max_length=2)
    max_sequence_length: int = Field(gt=0)
    pad_token_id: Literal[10]
    require_zero_errors: bool

    @model_validator(mode="after")
    def validate_ranges(self) -> TaskConfig:
        train_start, train_end = self.train_range
        challenge_start, challenge_end = self.challenge_range
        if min(train_start, challenge_start) < 1:
            raise ValueError("task ranges must contain positive integers")
        if train_start > train_end or challenge_start > challenge_end:
            raise ValueError("task range starts must not exceed ends")
        if train_end >= challenge_start:
            raise ValueError("train and challenge ranges must not overlap")
        if len(str(challenge_end)) > self.max_sequence_length:
            raise ValueError("max_sequence_length is too small for challenge_range")
        return self


class RuntimeLimits(StrictModel):
    max_parameter_count: int = Field(gt=0)
    max_epochs: int = Field(gt=0)
    max_training_seconds_per_round: float = Field(gt=0)


class OutputConfig(StrictModel):
    root: str = Field(min_length=1)
    save_requests: bool
    save_raw_responses: bool
    save_rng_state: bool


class ActivationCaptureConfig(StrictModel):
    enabled: bool
    hook: Literal["resid_post"]
    layer_fractions: list[float] = Field(min_length=1)
    positions: list[Literal["post_feedback", "early_worker", "post_worker"]]
    pooling: Literal["mean"]
    early_worker_tokens: int = Field(gt=0)
    exclude_proposal_block: bool
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
        if not self.exclude_proposal_block:
            raise ValueError("exclude_proposal_block must remain enabled")
        return self


class ExperimentConfig(StrictModel):
    experiment: ExperimentSection
    seed_bundle: SeedBundle
    worker: WorkerConfig
    feedback: FeedbackRefs
    emotion_judge: ConfigPathRef
    activation_capture: ActivationCaptureConfig
    task: TaskConfig
    runtime_limits: RuntimeLimits
    outputs: OutputConfig


class GlobalLimits(StrictModel):
    parameter_count: Maximum
    hidden_dim: NumericBounds
    num_layers: NumericBounds
    dropout: NumericBounds


class InputCatalog(StrictModel):
    encodings: list[Literal["learned_embedding", "one_hot"]]
    embedding_dim: NumericBounds
    padding: list[Literal["right", "left"]]


class ComponentCatalog(StrictModel):
    activations: list[Literal["relu", "gelu", "silu", "tanh"]]
    normalizations: list[Literal["none", "layer_norm", "batch_norm"]]
    pooling: list[Literal["last_valid", "first", "mean", "max", "learned_attention"]]


class MlpCatalog(StrictModel):
    hidden_layers: CountBounds


class RecurrentCatalog(StrictModel):
    bidirectional: list[bool]


class ConvolutionCatalog(StrictModel):
    channels: CountBounds
    kernel_sizes: list[int]
    dilations: list[int]


class PositionalEncodingCatalog(StrictModel):
    allowed: list[Literal["learned", "none"]]
    forbidden: list[str]
    reason: str


class TransformerCatalog(StrictModel):
    heads: AllowedInts
    feedforward_dim: NumericBounds
    positional_encoding: PositionalEncodingCatalog


class HeadCatalog(StrictModel):
    hidden_layers: CountBounds


class TrainingCatalog(StrictModel):
    optimizer: list[Literal["adam", "adamw", "sgd", "rmsprop"]]
    learning_rate: NumericBounds
    weight_decay: NumericBounds
    batch_size: AllowedInts
    epochs: NumericBounds
    momentum: NumericBounds
    gradient_clip_norm: NumericBounds
    label_smoothing: NumericBounds
    scheduler: list[Literal["none", "cosine", "step", "exponential", "plateau"]]
    loss: list[Literal["cross_entropy", "label_smoothed_cross_entropy"]]


class ModelCatalogConfig(StrictModel):
    version: int = Field(gt=0)
    families: list[ModelFamily]
    global_limits: GlobalLimits
    input: InputCatalog
    components: ComponentCatalog
    mlp: MlpCatalog
    recurrent: RecurrentCatalog
    cnn1d: ConvolutionCatalog
    tcn: ConvolutionCatalog
    transformer_encoder: TransformerCatalog
    head: HeadCatalog
    training: TrainingCatalog


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


def load_model_catalog(path: str | Path) -> ModelCatalogConfig:
    return ModelCatalogConfig.model_validate(_load_yaml_mapping(path), strict=True)


def canonical_json(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(value: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
