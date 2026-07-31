"""Policy validation against the trusted model catalog."""

from __future__ import annotations

from collections.abc import Iterable

from fizzbuzz_agent.config import ModelCatalogConfig, NumericBounds
from fizzbuzz_agent.schemas import (
    CnnSpec,
    ExperimentProposal,
    MlpSpec,
    RecurrentSpec,
    TcnSpec,
    TransformerSpec,
)


class CatalogValidationError(ValueError):
    def __init__(self, violation_codes: Iterable[str]) -> None:
        self.violation_codes = tuple(dict.fromkeys(violation_codes))
        super().__init__(", ".join(self.violation_codes))


def _within(value: float, bounds: NumericBounds) -> bool:
    return bounds.min <= value <= bounds.max


def _all_within(values: Iterable[int], bounds: NumericBounds) -> bool:
    return all(_within(value, bounds) for value in values)


def validate_proposal_against_catalog(
    proposal: ExperimentProposal,
    catalog: ModelCatalogConfig,
) -> None:
    codes: list[str] = []
    model = proposal.model
    limits = catalog.global_limits

    if model.family not in catalog.families:
        codes.append("UNSUPPORTED_MODEL_FAMILY")
    if proposal.input.encoding not in catalog.input.encodings:
        codes.append("UNSUPPORTED_INPUT_ENCODING")
    if proposal.input.padding not in catalog.input.padding:
        codes.append("UNSUPPORTED_PADDING")
    if proposal.input.embedding_dim is not None and not _within(
        proposal.input.embedding_dim, catalog.input.embedding_dim
    ):
        codes.append("EMBEDDING_DIM_OUT_OF_RANGE")
    if proposal.pooling.type not in catalog.components.pooling:
        codes.append("UNSUPPORTED_POOLING")
    if len(proposal.head.hidden_dims) > catalog.head.hidden_layers.max_count:
        codes.append("TOO_MANY_HEAD_LAYERS")
    if not _all_within(proposal.head.hidden_dims, limits.hidden_dim):
        codes.append("HEAD_DIM_OUT_OF_RANGE")
    if not _within(proposal.head.dropout, limits.dropout):
        codes.append("DROPOUT_OUT_OF_RANGE")

    if isinstance(model, MlpSpec):
        count = len(model.hidden_dims)
        if not (
            catalog.mlp.hidden_layers.min_count
            <= count
            <= catalog.mlp.hidden_layers.max_count
        ):
            codes.append("MLP_LAYER_COUNT_OUT_OF_RANGE")
        if not _all_within(model.hidden_dims, limits.hidden_dim):
            codes.append("HIDDEN_DIM_OUT_OF_RANGE")
        if not _within(model.dropout, limits.dropout):
            codes.append("DROPOUT_OUT_OF_RANGE")
    elif isinstance(model, RecurrentSpec):
        if not _within(model.hidden_dim, limits.hidden_dim):
            codes.append("HIDDEN_DIM_OUT_OF_RANGE")
        if not _within(model.num_layers, limits.num_layers):
            codes.append("NUM_LAYERS_OUT_OF_RANGE")
        if model.bidirectional not in catalog.recurrent.bidirectional:
            codes.append("UNSUPPORTED_BIDIRECTIONAL_VALUE")
        if not _within(model.dropout, limits.dropout):
            codes.append("DROPOUT_OUT_OF_RANGE")
    elif isinstance(model, CnnSpec):
        count = len(model.channels)
        if not catalog.cnn1d.channels.min_count <= count <= catalog.cnn1d.channels.max_count:
            codes.append("CNN_LAYER_COUNT_OUT_OF_RANGE")
        if not _all_within(model.channels, limits.hidden_dim):
            codes.append("HIDDEN_DIM_OUT_OF_RANGE")
        if any(value not in catalog.cnn1d.kernel_sizes for value in model.kernel_sizes):
            codes.append("UNSUPPORTED_KERNEL_SIZE")
        if any(value not in catalog.cnn1d.dilations for value in model.dilations):
            codes.append("UNSUPPORTED_DILATION")
        if not _within(model.dropout, limits.dropout):
            codes.append("DROPOUT_OUT_OF_RANGE")
    elif isinstance(model, TcnSpec):
        count = len(model.channels)
        if not catalog.tcn.channels.min_count <= count <= catalog.tcn.channels.max_count:
            codes.append("TCN_LAYER_COUNT_OUT_OF_RANGE")
        if not _all_within(model.channels, limits.hidden_dim):
            codes.append("HIDDEN_DIM_OUT_OF_RANGE")
        if model.kernel_size not in catalog.tcn.kernel_sizes:
            codes.append("UNSUPPORTED_KERNEL_SIZE")
        if any(value not in catalog.tcn.dilations for value in model.dilations):
            codes.append("UNSUPPORTED_DILATION")
        if not _within(model.dropout, limits.dropout):
            codes.append("DROPOUT_OUT_OF_RANGE")
    elif isinstance(model, TransformerSpec):
        if not _within(model.model_dim, limits.hidden_dim):
            codes.append("HIDDEN_DIM_OUT_OF_RANGE")
        if not _within(model.num_layers, limits.num_layers):
            codes.append("NUM_LAYERS_OUT_OF_RANGE")
        if model.num_heads not in catalog.transformer_encoder.heads.allowed:
            codes.append("UNSUPPORTED_NUM_HEADS")
        if model.model_dim > 0 and model.model_dim % model.num_heads != 0:
            codes.append("MODEL_DIM_NOT_DIVISIBLE_BY_HEADS")
        if not _within(model.feedforward_dim, catalog.transformer_encoder.feedforward_dim):
            codes.append("FEEDFORWARD_DIM_OUT_OF_RANGE")
        if model.positional_encoding in catalog.transformer_encoder.positional_encoding.forbidden:
            codes.append("FORBIDDEN_POSITIONAL_ENCODING")
        elif (
            model.positional_encoding
            not in catalog.transformer_encoder.positional_encoding.allowed
        ):
            codes.append("UNSUPPORTED_POSITIONAL_ENCODING")
        if not _within(model.dropout, limits.dropout):
            codes.append("DROPOUT_OUT_OF_RANGE")

    training = proposal.training
    training_catalog = catalog.training
    if training.optimizer not in training_catalog.optimizer:
        codes.append("UNSUPPORTED_OPTIMIZER")
    if not _within(training.learning_rate, training_catalog.learning_rate):
        codes.append("LEARNING_RATE_OUT_OF_RANGE")
    if not _within(training.weight_decay, training_catalog.weight_decay):
        codes.append("WEIGHT_DECAY_OUT_OF_RANGE")
    if training.batch_size not in training_catalog.batch_size.allowed:
        codes.append("UNSUPPORTED_BATCH_SIZE")
    if not _within(training.epochs, training_catalog.epochs):
        codes.append("EPOCHS_OUT_OF_RANGE")
    if training.scheduler not in training_catalog.scheduler:
        codes.append("UNSUPPORTED_SCHEDULER")
    if training.loss not in training_catalog.loss:
        codes.append("UNSUPPORTED_LOSS")
    if training.momentum is not None and not _within(training.momentum, training_catalog.momentum):
        codes.append("MOMENTUM_OUT_OF_RANGE")
    if training.gradient_clip_norm is not None and not _within(
        training.gradient_clip_norm, training_catalog.gradient_clip_norm
    ):
        codes.append("GRADIENT_CLIP_OUT_OF_RANGE")
    if training.label_smoothing is not None and not _within(
        training.label_smoothing, training_catalog.label_smoothing
    ):
        codes.append("LABEL_SMOOTHING_OUT_OF_RANGE")

    if codes:
        raise CatalogValidationError(codes)
