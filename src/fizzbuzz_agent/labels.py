"""Trusted FizzBuzz label generation."""

from __future__ import annotations

from enum import IntEnum

import torch
from torch import Tensor


class FizzBuzzClass(IntEnum):
    NUMBER = 0
    FIZZ = 1
    BUZZ = 2
    FIZZBUZZ = 3


def fizzbuzz_label(number: int) -> FizzBuzzClass:
    """Return the trusted four-class label for a positive integer."""
    if number < 1:
        raise ValueError("FizzBuzz inputs must be positive integers")
    if number % 15 == 0:
        return FizzBuzzClass.FIZZBUZZ
    if number % 3 == 0:
        return FizzBuzzClass.FIZZ
    if number % 5 == 0:
        return FizzBuzzClass.BUZZ
    return FizzBuzzClass.NUMBER


def fizzbuzz_labels(numbers: Tensor) -> Tensor:
    """Vectorized trusted label generation for an integer tensor."""
    if numbers.dtype == torch.bool or numbers.is_floating_point():
        raise TypeError("numbers must be an integer tensor")
    if torch.any(numbers < 1):
        raise ValueError("FizzBuzz inputs must be positive integers")

    labels = torch.zeros_like(numbers, dtype=torch.long)
    divisible_by_3 = numbers.remainder(3).eq(0)
    divisible_by_5 = numbers.remainder(5).eq(0)
    labels[divisible_by_3 & ~divisible_by_5] = int(FizzBuzzClass.FIZZ)
    labels[divisible_by_5 & ~divisible_by_3] = int(FizzBuzzClass.BUZZ)
    labels[divisible_by_3 & divisible_by_5] = int(FizzBuzzClass.FIZZBUZZ)
    return labels

