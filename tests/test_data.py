from __future__ import annotations

import pytest
import torch

from fizzbuzz_agent.data import DigitFizzBuzzDataset, encode_digit_sequences
from fizzbuzz_agent.labels import FizzBuzzClass, fizzbuzz_label, fizzbuzz_labels


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (1, FizzBuzzClass.NUMBER),
        (3, FizzBuzzClass.FIZZ),
        (5, FizzBuzzClass.BUZZ),
        (15, FizzBuzzClass.FIZZBUZZ),
        (9999, FizzBuzzClass.FIZZ),
        (10005, FizzBuzzClass.FIZZBUZZ),
    ],
)
def test_scalar_labels(number: int, expected: FizzBuzzClass) -> None:
    assert fizzbuzz_label(number) == expected


def test_vectorized_labels_match_scalar() -> None:
    numbers = torch.arange(1, 1000)
    expected = torch.tensor([int(fizzbuzz_label(int(number))) for number in numbers])
    assert torch.equal(fizzbuzz_labels(numbers), expected)


def test_digit_encoding_padding_and_order() -> None:
    numbers = torch.tensor([7, 1275])
    right = encode_digit_sequences(numbers, max_length=6, padding="right")
    left = encode_digit_sequences(numbers, max_length=6, padding="left")

    assert right.input_ids.tolist() == [[7, 10, 10, 10, 10, 10], [1, 2, 7, 5, 10, 10]]
    assert right.attention_mask.tolist() == [
        [True, False, False, False, False, False],
        [True, True, True, True, False, False],
    ]
    assert left.input_ids.tolist() == [[10, 10, 10, 10, 10, 7], [10, 10, 1, 2, 7, 5]]


def test_full_range_class_counts() -> None:
    train = DigitFizzBuzzDataset(1, 9999, max_length=6, padding="right")
    challenge = DigitFizzBuzzDataset(10000, 99999, max_length=6, padding="right")

    assert train.class_counts() == (5333, 2667, 1333, 666)
    assert challenge.class_counts() == (48000, 24000, 12000, 6000)
    assert len(challenge) == 90000


def test_encoding_rejects_too_short_max_length() -> None:
    with pytest.raises(ValueError, match="too small"):
        encode_digit_sequences(torch.tensor([10000]), max_length=4, padding="right")

