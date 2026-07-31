"""Shared trusted model components."""

from __future__ import annotations

from typing import cast

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from fizzbuzz_agent.schemas import HeadSpec, InputSpec, PoolingSpec

DIGIT_VOCAB_SIZE = 10
PAD_TOKEN_ID = 10
MODEL_VOCAB_SIZE = 11


def make_activation(name: str) -> nn.Module:
    activations: dict[str, type[nn.Module]] = {
        "relu": nn.ReLU,
        "gelu": nn.GELU,
        "silu": nn.SiLU,
        "tanh": nn.Tanh,
    }
    try:
        return activations[name]()
    except KeyError as exc:  # pragma: no cover - guarded by schema/catalog
        raise ValueError(f"Unsupported activation: {name}") from exc


def make_vector_normalization(name: str, dimension: int) -> nn.Module:
    if name == "none":
        return nn.Identity()
    if name == "layer_norm":
        return nn.LayerNorm(dimension)
    if name == "batch_norm":
        return nn.BatchNorm1d(dimension)
    raise ValueError(f"Unsupported normalization: {name}")


class ChannelNormalization(nn.Module):
    """Normalization for tensors shaped [batch, channels, sequence]."""

    def __init__(self, name: str, channels: int) -> None:
        super().__init__()
        self.name = name
        if name == "none":
            self.normalization: nn.Module = nn.Identity()
        elif name == "batch_norm":
            self.normalization = nn.BatchNorm1d(channels)
        elif name == "layer_norm":
            self.normalization = nn.LayerNorm(channels)
        else:  # pragma: no cover - guarded by schema/catalog
            raise ValueError(f"Unsupported normalization: {name}")

    def forward(self, values: Tensor) -> Tensor:
        if self.name == "layer_norm":
            normalized = cast(Tensor, self.normalization(values.transpose(1, 2)))
            return normalized.transpose(1, 2)
        return cast(Tensor, self.normalization(values))


class DigitInputEncoder(nn.Module):
    def __init__(self, spec: InputSpec, *, pad_token_id: int = PAD_TOKEN_ID) -> None:
        super().__init__()
        self.encoding = spec.encoding
        self.pad_token_id = pad_token_id
        if spec.encoding == "learned_embedding":
            if spec.embedding_dim is None:  # pragma: no cover - guarded by schema
                raise ValueError("embedding_dim is required")
            self.output_dim = spec.embedding_dim
            self.embedding: nn.Module | None = nn.Embedding(
                MODEL_VOCAB_SIZE,
                spec.embedding_dim,
                padding_idx=pad_token_id,
            )
        else:
            self.output_dim = MODEL_VOCAB_SIZE
            self.embedding = None

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        if self.embedding is not None:
            encoded = cast(Tensor, self.embedding(input_ids))
        else:
            encoded = F.one_hot(input_ids, num_classes=MODEL_VOCAB_SIZE).to(torch.float32)
        return encoded * attention_mask.unsqueeze(-1).to(encoded.dtype)


def compact_valid_tokens(values: Tensor, attention_mask: Tensor) -> tuple[Tensor, Tensor]:
    """Move valid tokens left without changing their order."""
    compacted = torch.zeros_like(values)
    lengths = attention_mask.sum(dim=1)
    for row in range(values.shape[0]):
        length = int(lengths[row].item())
        compacted[row, :length] = values[row, attention_mask[row]]
    positions = torch.arange(values.shape[1], device=values.device).unsqueeze(0)
    compacted_mask = positions < lengths.unsqueeze(1)
    return compacted, compacted_mask


class SequencePooling(nn.Module):
    def __init__(self, spec: PoolingSpec, dimension: int) -> None:
        super().__init__()
        self.pooling_type = spec.type
        self.attention = (
            nn.Linear(dimension, 1, bias=False)
            if spec.type == "learned_attention"
            else None
        )

    def forward(self, values: Tensor, attention_mask: Tensor) -> Tensor:
        if torch.any(attention_mask.sum(dim=1) == 0):
            raise ValueError("Every sequence must contain at least one valid token")
        if self.pooling_type == "first":
            indices = attention_mask.to(torch.int64).argmax(dim=1)
            return values[torch.arange(values.shape[0], device=values.device), indices]
        if self.pooling_type == "last_valid":
            positions = torch.arange(values.shape[1], device=values.device).unsqueeze(0)
            indices = positions.masked_fill(~attention_mask, -1).max(dim=1).values
            return values[torch.arange(values.shape[0], device=values.device), indices]
        if self.pooling_type == "mean":
            mask = attention_mask.unsqueeze(-1).to(values.dtype)
            return (values * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)
        if self.pooling_type == "max":
            minimum = torch.finfo(values.dtype).min
            return values.masked_fill(~attention_mask.unsqueeze(-1), minimum).max(dim=1).values
        if self.attention is None:  # pragma: no cover - defensive
            raise RuntimeError("learned attention pooling was not initialized")
        scores = self.attention(values).squeeze(-1).masked_fill(~attention_mask, float("-inf"))
        weights = torch.softmax(scores, dim=1)
        return torch.sum(values * weights.unsqueeze(-1), dim=1)


class ClassificationHead(nn.Module):
    def __init__(self, input_dim: int, spec: HeadSpec, *, num_classes: int = 4) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current_dim = input_dim
        for hidden_dim in spec.hidden_dims:
            layers.extend(
                [
                    nn.Linear(current_dim, hidden_dim),
                    make_vector_normalization(spec.normalization, hidden_dim),
                    make_activation(spec.activation),
                    nn.Dropout(spec.dropout),
                ]
            )
            current_dim = hidden_dim
        layers.append(nn.Linear(current_dim, num_classes))
        self.network = nn.Sequential(*layers)

    def forward(self, values: Tensor) -> Tensor:
        return cast(Tensor, self.network(values))
