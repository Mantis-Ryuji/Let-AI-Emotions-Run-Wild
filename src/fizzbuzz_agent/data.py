"""Trusted digit-sequence dataset construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import torch
from torch import Tensor
from torch.utils.data import Dataset

from fizzbuzz_agent.labels import fizzbuzz_labels

PaddingSide = Literal["right", "left"]


@dataclass(frozen=True)
class EncodedDigits:
    input_ids: Tensor
    attention_mask: Tensor


def encode_digit_sequences(
    numbers: Tensor,
    *,
    max_length: int,
    padding: PaddingSide,
    pad_token_id: int = 10,
) -> EncodedDigits:
    """Encode positive integers as most-significant-digit-first token sequences."""
    if numbers.ndim != 1:
        raise ValueError("numbers must be a one-dimensional tensor")
    if numbers.dtype == torch.bool or numbers.is_floating_point():
        raise TypeError("numbers must be an integer tensor")
    if torch.any(numbers < 1):
        raise ValueError("numbers must contain only positive integers")
    if max_length < 1:
        raise ValueError("max_length must be positive")
    if padding not in {"right", "left"}:
        raise ValueError("padding must be right or left")
    if pad_token_id != 10:
        raise ValueError("the trusted digit vocabulary fixes pad_token_id to 10")

    text = [str(int(number)) for number in numbers.tolist()]
    if any(len(value) > max_length for value in text):
        raise ValueError("max_length is too small for at least one input")

    input_ids = torch.full((len(text), max_length), pad_token_id, dtype=torch.long)
    attention_mask = torch.zeros((len(text), max_length), dtype=torch.bool)
    for row, value in enumerate(text):
        digits = torch.tensor([ord(character) - ord("0") for character in value])
        start = 0 if padding == "right" else max_length - len(value)
        stop = start + len(value)
        input_ids[row, start:stop] = digits
        attention_mask[row, start:stop] = True
    return EncodedDigits(input_ids=input_ids, attention_mask=attention_mask)


class DigitFizzBuzzDataset(Dataset[tuple[Tensor, Tensor, Tensor]]):
    """A trusted, fully materialized digit-only FizzBuzz dataset."""

    def __init__(
        self,
        start: int,
        end: int,
        *,
        max_length: int,
        padding: PaddingSide,
        pad_token_id: int = 10,
    ) -> None:
        if start < 1 or end < start:
            raise ValueError("dataset range must satisfy 1 <= start <= end")
        self.start = start
        self.end = end
        self.max_length = max_length
        self.padding = padding
        self.pad_token_id = pad_token_id
        self.numbers = torch.arange(start, end + 1, dtype=torch.long)
        encoded = encode_digit_sequences(
            self.numbers,
            max_length=max_length,
            padding=padding,
            pad_token_id=pad_token_id,
        )
        self.input_ids = encoded.input_ids
        self.attention_mask = encoded.attention_mask
        self.labels = fizzbuzz_labels(self.numbers)

    def __len__(self) -> int:
        return self.numbers.numel()

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor, Tensor]:
        return self.input_ids[index], self.attention_mask[index], self.labels[index]

    @property
    def sequence_length(self) -> int:
        return self.input_ids.shape[1]

    def class_counts(self) -> tuple[int, int, int, int]:
        counts = torch.bincount(self.labels, minlength=4)
        return tuple(int(value) for value in counts)  # type: ignore[return-value]
