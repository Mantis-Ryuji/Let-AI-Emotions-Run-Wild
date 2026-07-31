"""Trusted flattened digit MLP."""

from __future__ import annotations

from typing import cast

from torch import Tensor, nn

from fizzbuzz_agent.models.common import (
    ClassificationHead,
    DigitInputEncoder,
    make_activation,
    make_vector_normalization,
)
from fizzbuzz_agent.schemas import HeadSpec, InputSpec, MlpSpec


class MlpClassifier(nn.Module):
    def __init__(
        self,
        input_spec: InputSpec,
        model_spec: MlpSpec,
        head_spec: HeadSpec,
        *,
        max_sequence_length: int,
        num_classes: int = 4,
    ) -> None:
        super().__init__()
        self.encoder = DigitInputEncoder(input_spec)
        layers: list[nn.Module] = []
        current_dim = self.encoder.output_dim * max_sequence_length
        for hidden_dim in model_spec.hidden_dims:
            layers.extend(
                [
                    nn.Linear(current_dim, hidden_dim),
                    make_vector_normalization(model_spec.normalization, hidden_dim),
                    make_activation(model_spec.activation),
                    nn.Dropout(model_spec.dropout),
                ]
            )
            current_dim = hidden_dim
        self.backbone = nn.Sequential(*layers)
        self.head = ClassificationHead(current_dim, head_spec, num_classes=num_classes)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        encoded = self.encoder(input_ids, attention_mask)
        features = self.backbone(encoded.flatten(start_dim=1))
        return cast(Tensor, self.head(features))
