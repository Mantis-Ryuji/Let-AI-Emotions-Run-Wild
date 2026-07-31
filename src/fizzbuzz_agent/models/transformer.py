"""Trusted Transformer Encoder classifier without periodic positional features."""

from __future__ import annotations

from typing import cast

import torch
from torch import Tensor, nn

from fizzbuzz_agent.models.common import ClassificationHead, DigitInputEncoder, SequencePooling
from fizzbuzz_agent.schemas import HeadSpec, InputSpec, PoolingSpec, TransformerSpec


class TransformerEncoderClassifier(nn.Module):
    def __init__(
        self,
        input_spec: InputSpec,
        model_spec: TransformerSpec,
        pooling_spec: PoolingSpec,
        head_spec: HeadSpec,
        *,
        max_sequence_length: int,
        num_classes: int = 4,
    ) -> None:
        super().__init__()
        self.encoder = DigitInputEncoder(input_spec)
        self.input_projection: nn.Module = (
            nn.Identity()
            if self.encoder.output_dim == model_spec.model_dim
            else nn.Linear(self.encoder.output_dim, model_spec.model_dim)
        )
        if model_spec.positional_encoding == "learned":
            self.position_embedding: nn.Parameter | None = nn.Parameter(
                torch.empty(max_sequence_length, model_spec.model_dim)
            )
            nn.init.normal_(self.position_embedding, mean=0.0, std=0.02)
        elif model_spec.positional_encoding == "none":
            self.position_embedding = None
        else:  # pragma: no cover - guarded by catalog
            raise ValueError("Only learned or none positional encoding is trusted")
        layer = nn.TransformerEncoderLayer(
            d_model=model_spec.model_dim,
            nhead=model_spec.num_heads,
            dim_feedforward=model_spec.feedforward_dim,
            dropout=model_spec.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=model_spec.pre_norm,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=model_spec.num_layers)
        self.pooling = SequencePooling(pooling_spec, model_spec.model_dim)
        self.head = ClassificationHead(model_spec.model_dim, head_spec, num_classes=num_classes)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        values = self.input_projection(self.encoder(input_ids, attention_mask))
        if self.position_embedding is not None:
            values = values + self.position_embedding[: values.shape[1]].unsqueeze(0)
        values = cast(
            Tensor,
            self.transformer(values, src_key_padding_mask=~attention_mask),
        )
        values = values * attention_mask.unsqueeze(-1).to(values.dtype)
        return cast(Tensor, self.head(self.pooling(values, attention_mask)))
