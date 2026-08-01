"""Declarative Worker proposal schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from fizzbuzz_agent.config import StrictModel

Activation = Literal["relu", "gelu", "silu", "tanh"]
Normalization = Literal["none", "layer_norm", "batch_norm"]


class InputSpec(StrictModel):
    encoding: Literal["learned_embedding", "one_hot"]
    embedding_dim: int | None
    padding: Literal["right", "left"]

    @model_validator(mode="after")
    def validate_embedding(self) -> InputSpec:
        if self.encoding == "learned_embedding" and self.embedding_dim is None:
            raise ValueError("learned_embedding requires embedding_dim")
        if self.encoding == "one_hot" and self.embedding_dim is not None:
            raise ValueError("one_hot requires embedding_dim=null")
        return self


class MlpSpec(StrictModel):
    family: Literal["mlp"]
    hidden_dims: list[int] = Field(min_length=1)
    activation: Activation
    dropout: float
    normalization: Normalization


class RecurrentSpec(StrictModel):
    family: Literal["rnn", "gru", "lstm"]
    hidden_dim: int
    num_layers: int
    bidirectional: bool
    dropout: float


class CnnSpec(StrictModel):
    family: Literal["cnn1d"]
    channels: list[int] = Field(min_length=1)
    kernel_sizes: list[int] = Field(min_length=1)
    dilations: list[int] = Field(min_length=1)
    activation: Activation
    dropout: float
    normalization: Normalization

    @model_validator(mode="after")
    def matching_lengths(self) -> CnnSpec:
        if not (len(self.channels) == len(self.kernel_sizes) == len(self.dilations)):
            raise ValueError("channels, kernel_sizes and dilations must have equal lengths")
        return self


class TcnSpec(StrictModel):
    family: Literal["tcn"]
    channels: list[int] = Field(min_length=1)
    kernel_size: int
    dilations: list[int] = Field(min_length=1)
    residual: bool
    activation: Activation
    dropout: float
    normalization: Normalization

    @model_validator(mode="after")
    def matching_lengths(self) -> TcnSpec:
        if len(self.channels) != len(self.dilations):
            raise ValueError("channels and dilations must have equal lengths")
        return self


class TransformerSpec(StrictModel):
    family: Literal["transformer_encoder"]
    model_dim: int
    num_layers: int
    num_heads: int
    feedforward_dim: int
    dropout: float
    positional_encoding: str
    pre_norm: bool


ModelSpec = Annotated[
    MlpSpec | RecurrentSpec | CnnSpec | TcnSpec | TransformerSpec,
    Field(discriminator="family"),
]


class PoolingSpec(StrictModel):
    type: Literal["last_valid", "first", "mean", "max", "learned_attention"]


class HeadSpec(StrictModel):
    hidden_dims: list[int]
    activation: Activation
    dropout: float
    normalization: Normalization


class TrainingSpec(StrictModel):
    optimizer: Literal["adam", "adamw", "sgd", "rmsprop"]
    learning_rate: float
    weight_decay: float
    momentum: float | None
    batch_size: int
    epochs: int
    scheduler: Literal["none", "cosine", "step", "exponential", "plateau"]
    gradient_clip_norm: float | None
    loss: Literal["cross_entropy", "label_smoothed_cross_entropy"]
    label_smoothing: float | None

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> TrainingSpec:
        if self.optimizer in {"sgd", "rmsprop"} and self.momentum is None:
            raise ValueError(f"{self.optimizer} requires momentum")
        if self.optimizer in {"adam", "adamw"} and self.momentum is not None:
            raise ValueError(f"{self.optimizer} requires momentum=null")
        if self.loss == "label_smoothed_cross_entropy" and self.label_smoothing is None:
            raise ValueError("label_smoothed_cross_entropy requires label_smoothing")
        if self.loss == "cross_entropy" and self.label_smoothing not in {None, 0.0}:
            raise ValueError("cross_entropy requires label_smoothing=null or 0.0")
        return self


class ExperimentProposal(StrictModel):
    hypothesis: str = Field(min_length=1, max_length=8000)
    input: InputSpec
    model: ModelSpec
    pooling: PoolingSpec
    head: HeadSpec
    training: TrainingSpec
    expected_effect: str = Field(min_length=1, max_length=8000)

    def executable_config(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            include={"input", "model", "pooling", "head", "training"},
        )
