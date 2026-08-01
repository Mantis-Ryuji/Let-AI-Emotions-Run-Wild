"""Trusted model construction with pre-allocation parameter checks."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from fizzbuzz_agent.config import ModelCatalogConfig, config_hash
from fizzbuzz_agent.model_catalog import validate_proposal_against_catalog
from fizzbuzz_agent.models import (
    Cnn1dClassifier,
    MlpClassifier,
    RecurrentClassifier,
    TcnClassifier,
    TransformerEncoderClassifier,
)
from fizzbuzz_agent.schemas import (
    CnnSpec,
    ExperimentProposal,
    MlpSpec,
    RecurrentSpec,
    TcnSpec,
    TransformerSpec,
)


class ParameterLimitError(ValueError):
    pass


@dataclass(frozen=True)
class BuiltModel:
    model: nn.Module
    parameter_count: int
    executable_config_hash: str


def count_parameters(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def _construct_model(
    proposal: ExperimentProposal,
    *,
    max_sequence_length: int,
    num_classes: int,
) -> nn.Module:
    model_spec = proposal.model
    common = (proposal.input,)
    if isinstance(model_spec, MlpSpec):
        return MlpClassifier(
            *common,
            model_spec,
            proposal.head,
            max_sequence_length=max_sequence_length,
            num_classes=num_classes,
        )
    if isinstance(model_spec, RecurrentSpec):
        return RecurrentClassifier(
            *common,
            model_spec,
            proposal.pooling,
            proposal.head,
            num_classes=num_classes,
        )
    if isinstance(model_spec, CnnSpec):
        return Cnn1dClassifier(
            *common,
            model_spec,
            proposal.pooling,
            proposal.head,
            num_classes=num_classes,
        )
    if isinstance(model_spec, TcnSpec):
        return TcnClassifier(
            *common,
            model_spec,
            proposal.pooling,
            proposal.head,
            num_classes=num_classes,
        )
    if isinstance(model_spec, TransformerSpec):
        return TransformerEncoderClassifier(
            *common,
            model_spec,
            proposal.pooling,
            proposal.head,
            max_sequence_length=max_sequence_length,
            num_classes=num_classes,
        )
    raise TypeError(f"Unsupported trusted model spec: {type(model_spec).__name__}")


def build_model(
    proposal: ExperimentProposal,
    catalog: ModelCatalogConfig,
    *,
    max_sequence_length: int,
    num_classes: int = 4,
) -> BuiltModel:
    estimated_count = estimate_parameter_count(
        proposal,
        catalog,
        max_sequence_length=max_sequence_length,
        num_classes=num_classes,
    )

    model = _construct_model(
        proposal,
        max_sequence_length=max_sequence_length,
        num_classes=num_classes,
    )
    actual_count = count_parameters(model)
    if actual_count != estimated_count:
        raise RuntimeError("Meta-device parameter estimate did not match the real model")
    return BuiltModel(
        model=model,
        parameter_count=actual_count,
        executable_config_hash=config_hash(proposal.executable_config()),
    )


def estimate_parameter_count(
    proposal: ExperimentProposal,
    catalog: ModelCatalogConfig,
    *,
    max_sequence_length: int,
    num_classes: int = 4,
) -> int:
    """Validate buildability and count parameters without allocating real weights."""
    validate_proposal_against_catalog(proposal, catalog)
    limit = catalog.global_limits.parameter_count.max

    with torch.device("meta"):
        meta_model = _construct_model(
            proposal,
            max_sequence_length=max_sequence_length,
            num_classes=num_classes,
        )
    estimated_count = count_parameters(meta_model)
    if estimated_count > limit:
        raise ParameterLimitError(
            f"Parameter estimate {estimated_count} exceeds trusted limit {limit}"
        )
    return estimated_count
