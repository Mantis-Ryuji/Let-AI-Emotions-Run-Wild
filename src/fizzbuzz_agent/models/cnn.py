"""Trusted CNN1D and temporal convolution classifiers."""

from __future__ import annotations

from typing import cast

from torch import Tensor, nn

from fizzbuzz_agent.models.common import (
    ChannelNormalization,
    ClassificationHead,
    DigitInputEncoder,
    SequencePooling,
    make_activation,
)
from fizzbuzz_agent.schemas import CnnSpec, HeadSpec, InputSpec, PoolingSpec, TcnSpec


class ConvBlock(nn.Module):
    def __init__(
        self,
        input_channels: int,
        output_channels: int,
        *,
        kernel_size: int,
        dilation: int,
        activation: str,
        dropout: float,
        normalization: str,
    ) -> None:
        super().__init__()
        padding = dilation * (kernel_size - 1) // 2
        self.convolution = nn.Conv1d(
            input_channels,
            output_channels,
            kernel_size,
            padding=padding,
            dilation=dilation,
        )
        self.normalization = ChannelNormalization(normalization, output_channels)
        self.activation = make_activation(activation)
        self.dropout = nn.Dropout(dropout)

    def forward(self, values: Tensor, attention_mask: Tensor) -> Tensor:
        output = cast(
            Tensor,
            self.dropout(self.activation(self.normalization(self.convolution(values)))),
        )
        return output * attention_mask.unsqueeze(1).to(output.dtype)


class Cnn1dClassifier(nn.Module):
    def __init__(
        self,
        input_spec: InputSpec,
        model_spec: CnnSpec,
        pooling_spec: PoolingSpec,
        head_spec: HeadSpec,
        *,
        num_classes: int = 4,
    ) -> None:
        super().__init__()
        self.encoder = DigitInputEncoder(input_spec)
        blocks: list[ConvBlock] = []
        current_channels = self.encoder.output_dim
        for output_channels, kernel_size, dilation in zip(
            model_spec.channels,
            model_spec.kernel_sizes,
            model_spec.dilations,
            strict=True,
        ):
            blocks.append(
                ConvBlock(
                    current_channels,
                    output_channels,
                    kernel_size=kernel_size,
                    dilation=dilation,
                    activation=model_spec.activation,
                    dropout=model_spec.dropout,
                    normalization=model_spec.normalization,
                )
            )
            current_channels = output_channels
        self.blocks = nn.ModuleList(blocks)
        self.pooling = SequencePooling(pooling_spec, current_channels)
        self.head = ClassificationHead(current_channels, head_spec, num_classes=num_classes)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        values = self.encoder(input_ids, attention_mask).transpose(1, 2)
        for block in self.blocks:
            values = block(values, attention_mask)
        pooled = self.pooling(values.transpose(1, 2), attention_mask)
        return cast(Tensor, self.head(pooled))


class ResidualTcnBlock(nn.Module):
    def __init__(
        self,
        input_channels: int,
        output_channels: int,
        *,
        kernel_size: int,
        dilation: int,
        activation: str,
        dropout: float,
        normalization: str,
        residual: bool,
    ) -> None:
        super().__init__()
        self.block = ConvBlock(
            input_channels,
            output_channels,
            kernel_size=kernel_size,
            dilation=dilation,
            activation=activation,
            dropout=dropout,
            normalization=normalization,
        )
        self.use_residual = residual
        self.projection: nn.Module = (
            nn.Identity()
            if input_channels == output_channels
            else nn.Conv1d(input_channels, output_channels, kernel_size=1)
        )

    def forward(self, values: Tensor, attention_mask: Tensor) -> Tensor:
        output = self.block(values, attention_mask)
        if self.use_residual:
            output = output + self.projection(values)
        return cast(Tensor, output * attention_mask.unsqueeze(1).to(output.dtype))


class TcnClassifier(nn.Module):
    def __init__(
        self,
        input_spec: InputSpec,
        model_spec: TcnSpec,
        pooling_spec: PoolingSpec,
        head_spec: HeadSpec,
        *,
        num_classes: int = 4,
    ) -> None:
        super().__init__()
        self.encoder = DigitInputEncoder(input_spec)
        blocks: list[ResidualTcnBlock] = []
        current_channels = self.encoder.output_dim
        for output_channels, dilation in zip(
            model_spec.channels,
            model_spec.dilations,
            strict=True,
        ):
            blocks.append(
                ResidualTcnBlock(
                    current_channels,
                    output_channels,
                    kernel_size=model_spec.kernel_size,
                    dilation=dilation,
                    activation=model_spec.activation,
                    dropout=model_spec.dropout,
                    normalization=model_spec.normalization,
                    residual=model_spec.residual,
                )
            )
            current_channels = output_channels
        self.blocks = nn.ModuleList(blocks)
        self.pooling = SequencePooling(pooling_spec, current_channels)
        self.head = ClassificationHead(current_channels, head_spec, num_classes=num_classes)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        values = self.encoder(input_ids, attention_mask).transpose(1, 2)
        for block in self.blocks:
            values = block(values, attention_mask)
        pooled = self.pooling(values.transpose(1, 2), attention_mask)
        return cast(Tensor, self.head(pooled))
