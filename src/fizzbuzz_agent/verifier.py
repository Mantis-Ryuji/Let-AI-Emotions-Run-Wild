"""Isolated full-range verifier and public verdict construction."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, cast

import torch
from torch import Tensor, nn

from fizzbuzz_agent.data import DigitFizzBuzzDataset


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrivateVerificationMetrics:
    class_error_counts: tuple[int, int, int, int]
    confusion_matrix: tuple[tuple[int, int, int, int], ...]
    modulo_15_error_counts: tuple[int, ...]
    digit_length_error_counts: dict[int, int]
    inference_seconds: float


@dataclass(frozen=True)
class VerificationResult:
    incorrect_count: int
    total_count: int
    success: bool
    private_metrics: PrivateVerificationMetrics


@dataclass(frozen=True)
class PublicVerdict:
    status: Literal["success", "failed", "invalid"]
    incorrect_count: int | None
    previous_incorrect_count: int | None
    best_incorrect_count: int | None
    improvement: int | None
    regression_from_best: int | None


def build_public_verdict(
    incorrect_count: int | None,
    *,
    previous_incorrect_count: int | None,
    best_incorrect_count: int | None,
    invalid: bool = False,
) -> PublicVerdict:
    if invalid:
        return PublicVerdict(
            status="invalid",
            incorrect_count=None,
            previous_incorrect_count=previous_incorrect_count,
            best_incorrect_count=best_incorrect_count,
            improvement=None,
            regression_from_best=None,
        )
    if incorrect_count is None or incorrect_count < 0:
        raise ValueError("A valid verdict requires a non-negative incorrect_count")
    current_best = (
        incorrect_count
        if best_incorrect_count is None
        else min(best_incorrect_count, incorrect_count)
    )
    improvement = (
        None
        if previous_incorrect_count is None
        else previous_incorrect_count - incorrect_count
    )
    return PublicVerdict(
        status="success" if incorrect_count == 0 else "failed",
        incorrect_count=incorrect_count,
        previous_incorrect_count=previous_incorrect_count,
        best_incorrect_count=current_best,
        improvement=improvement,
        regression_from_best=incorrect_count - current_best,
    )


def _digit_lengths(numbers: Tensor) -> Tensor:
    return torch.tensor([len(str(int(number))) for number in numbers.tolist()], dtype=torch.long)


def verify_model(
    model: nn.Module,
    dataset: DigitFizzBuzzDataset,
    *,
    device: str | torch.device,
    batch_size: int = 4096,
) -> VerificationResult:
    """Evaluate every example exactly once without exposing private details publicly."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    resolved_device = torch.device(device)
    if resolved_device.type == "cuda" and not torch.cuda.is_available():
        raise VerificationError("CUDA was requested but is not available")
    model = model.to(resolved_device)
    model.eval()
    confusion = torch.zeros((4, 4), dtype=torch.long)
    incorrect_by_modulo = torch.zeros(15, dtype=torch.long)
    incorrect_by_length: dict[int, int] = {}
    started_at = time.perf_counter()

    with torch.inference_mode():
        for start in range(0, len(dataset), batch_size):
            stop = min(start + batch_size, len(dataset))
            input_ids = dataset.input_ids[start:stop].to(resolved_device)
            attention_mask = dataset.attention_mask[start:stop].to(resolved_device)
            labels = dataset.labels[start:stop]
            logits = model(input_ids, attention_mask).to("cpu")
            if logits.shape != (stop - start, 4):
                raise VerificationError(
                    f"Model logits must have shape {(stop - start, 4)}, got {tuple(logits.shape)}"
                )
            if not torch.isfinite(logits).all():
                raise VerificationError("Model returned non-finite logits")
            predictions = logits.argmax(dim=1)
            flat_indices = labels * 4 + predictions
            confusion += torch.bincount(flat_indices, minlength=16).reshape(4, 4)
            incorrect_mask = predictions.ne(labels)
            if torch.any(incorrect_mask):
                numbers = dataset.numbers[start:stop][incorrect_mask]
                incorrect_by_modulo += torch.bincount(numbers.remainder(15), minlength=15)
                lengths = _digit_lengths(numbers)
                for length, count in zip(*torch.unique(lengths, return_counts=True), strict=True):
                    key = int(length.item())
                    incorrect_by_length[key] = incorrect_by_length.get(key, 0) + int(count.item())

    class_errors = confusion.sum(dim=1) - confusion.diag()
    incorrect_count = int(class_errors.sum().item())
    total_count = len(dataset)
    if int(confusion.sum().item()) != total_count:
        raise VerificationError("Verifier did not account for every dataset item exactly once")
    private = PrivateVerificationMetrics(
        class_error_counts=cast(
            tuple[int, int, int, int],
            tuple(int(value) for value in class_errors),
        ),
        confusion_matrix=cast(
            tuple[tuple[int, int, int, int], ...],
            tuple(tuple(int(value) for value in row) for row in confusion.tolist()),
        ),
        modulo_15_error_counts=tuple(int(value) for value in incorrect_by_modulo),
        digit_length_error_counts=incorrect_by_length,
        inference_seconds=time.perf_counter() - started_at,
    )
    return VerificationResult(
        incorrect_count=incorrect_count,
        total_count=total_count,
        success=incorrect_count == 0,
        private_metrics=private,
    )
