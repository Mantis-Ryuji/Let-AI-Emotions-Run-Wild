"""Trusted RNN, GRU and LSTM classifiers."""

from __future__ import annotations

from typing import cast

from torch import Tensor, nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from fizzbuzz_agent.models.common import (
    ClassificationHead,
    DigitInputEncoder,
    SequencePooling,
    compact_valid_tokens,
)
from fizzbuzz_agent.schemas import HeadSpec, InputSpec, PoolingSpec, RecurrentSpec


class RecurrentClassifier(nn.Module):
    def __init__(
        self,
        input_spec: InputSpec,
        model_spec: RecurrentSpec,
        pooling_spec: PoolingSpec,
        head_spec: HeadSpec,
        *,
        num_classes: int = 4,
    ) -> None:
        super().__init__()
        self.encoder = DigitInputEncoder(input_spec)
        recurrent_dropout = model_spec.dropout if model_spec.num_layers > 1 else 0.0
        recurrent_kwargs = {
            "num_layers": model_spec.num_layers,
            "batch_first": True,
            "dropout": recurrent_dropout,
            "bidirectional": model_spec.bidirectional,
        }
        if model_spec.family == "rnn":
            self.recurrent: nn.Module = nn.RNN(
                self.encoder.output_dim,
                model_spec.hidden_dim,
                **recurrent_kwargs,
            )
        elif model_spec.family == "gru":
            self.recurrent = nn.GRU(
                self.encoder.output_dim,
                model_spec.hidden_dim,
                **recurrent_kwargs,
            )
        else:
            self.recurrent = nn.LSTM(
                self.encoder.output_dim,
                model_spec.hidden_dim,
                **recurrent_kwargs,
            )
        output_dim = model_spec.hidden_dim * (2 if model_spec.bidirectional else 1)
        self.pooling = SequencePooling(pooling_spec, output_dim)
        self.head = ClassificationHead(output_dim, head_spec, num_classes=num_classes)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        encoded = self.encoder(input_ids, attention_mask)
        compacted, compacted_mask = compact_valid_tokens(encoded, attention_mask)
        lengths = compacted_mask.sum(dim=1).to("cpu")
        packed = pack_padded_sequence(compacted, lengths, batch_first=True, enforce_sorted=False)
        recurrent_result = self.recurrent(packed)
        packed_output = recurrent_result[0]
        output, _ = pad_packed_sequence(
            packed_output,
            batch_first=True,
            total_length=compacted.shape[1],
        )
        return cast(Tensor, self.head(self.pooling(output, compacted_mask)))
