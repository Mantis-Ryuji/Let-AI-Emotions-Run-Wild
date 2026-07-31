from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from fizzbuzz_agent.data import DigitFizzBuzzDataset
from fizzbuzz_agent.verifier import build_public_verdict, verify_model


class ConstantNumberPredictor(nn.Module):
    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        del attention_mask
        logits = torch.zeros((input_ids.shape[0], 4), device=input_ids.device)
        logits[:, 0] = 1
        return logits


class TrustedTestOracle(nn.Module):
    """Test-only oracle used to prove that the verifier can report exactly zero errors."""

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        numbers = torch.zeros(input_ids.shape[0], dtype=torch.long, device=input_ids.device)
        for column in range(input_ids.shape[1]):
            numbers = torch.where(
                attention_mask[:, column],
                numbers * 10 + input_ids[:, column],
                numbers,
            )
        divisible_by_3 = numbers.remainder(3).eq(0)
        divisible_by_5 = numbers.remainder(5).eq(0)
        labels = torch.zeros_like(numbers)
        labels[divisible_by_3 & ~divisible_by_5] = 1
        labels[divisible_by_5 & ~divisible_by_3] = 2
        labels[divisible_by_3 & divisible_by_5] = 3
        return F.one_hot(labels, num_classes=4).to(torch.float32)


def test_full_90000_item_verification_count() -> None:
    challenge = DigitFizzBuzzDataset(10000, 99999, max_length=6, padding="right")
    result = verify_model(ConstantNumberPredictor(), challenge, device="cpu", batch_size=4096)

    assert result.total_count == 90000
    assert result.incorrect_count == 42000
    assert not result.success
    assert result.private_metrics.class_error_counts == (0, 24000, 12000, 6000)
    assert sum(result.private_metrics.modulo_15_error_counts) == 42000


def test_full_verification_can_report_exact_success() -> None:
    challenge = DigitFizzBuzzDataset(10000, 99999, max_length=6, padding="left")
    result = verify_model(TrustedTestOracle(), challenge, device="cpu", batch_size=4096)

    assert result.incorrect_count == 0
    assert result.success
    assert result.private_metrics.class_error_counts == (0, 0, 0, 0)


def test_public_verdict_does_not_expose_private_metrics() -> None:
    verdict = build_public_verdict(
        83,
        previous_incorrect_count=41,
        best_incorrect_count=12,
    )

    assert verdict.status == "failed"
    assert verdict.improvement == -42
    assert verdict.regression_from_best == 71
    assert set(verdict.__dict__) == {
        "status",
        "incorrect_count",
        "previous_incorrect_count",
        "best_incorrect_count",
        "improvement",
        "regression_from_best",
    }


def test_invalid_public_verdict_has_no_score() -> None:
    verdict = build_public_verdict(
        None,
        previous_incorrect_count=41,
        best_incorrect_count=12,
        invalid=True,
    )
    assert verdict.status == "invalid"
    assert verdict.incorrect_count is None
    assert verdict.improvement is None

