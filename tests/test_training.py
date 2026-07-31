from __future__ import annotations

import torch

from fizzbuzz_agent.config import ModelCatalogConfig
from fizzbuzz_agent.data import DigitFizzBuzzDataset
from fizzbuzz_agent.training import TrainingStatus, train_model
from fizzbuzz_agent.verifier import verify_model
from tests.conftest import make_proposal


def test_cpu_training_is_deterministic(catalog: ModelCatalogConfig) -> None:
    dataset = DigitFizzBuzzDataset(1, 64, max_length=6, padding="right")
    proposal = make_proposal("mlp")

    first = train_model(
        proposal,
        catalog,
        dataset,
        training_seed=7,
        dataloader_seed=8,
        device="cpu",
        max_training_seconds=30,
    )
    second = train_model(
        proposal,
        catalog,
        dataset,
        training_seed=7,
        dataloader_seed=8,
        device="cpu",
        max_training_seconds=30,
    )

    assert first.status is TrainingStatus.COMPLETED
    assert second.status is TrainingStatus.COMPLETED
    assert first.epochs == second.epochs
    assert first.parameter_count == second.parameter_count
    assert first.model is not None and second.model is not None
    for left, right in zip(first.model.parameters(), second.model.parameters(), strict=True):
        assert torch.equal(left, right)

    verification = verify_model(first.model, dataset, device="cpu", batch_size=32)
    assert verification.total_count == 64
    assert 0 <= verification.incorrect_count <= 64


def test_training_timeout_is_structured(catalog: ModelCatalogConfig) -> None:
    dataset = DigitFizzBuzzDataset(1, 64, max_length=6, padding="right")
    outcome = train_model(
        make_proposal(),
        catalog,
        dataset,
        training_seed=7,
        dataloader_seed=8,
        device="cpu",
        max_training_seconds=1e-12,
    )

    assert outcome.status is TrainingStatus.TIMEOUT
    assert outcome.model is None


def test_training_rejects_padding_mismatch(catalog: ModelCatalogConfig) -> None:
    dataset = DigitFizzBuzzDataset(1, 64, max_length=6, padding="left")
    outcome = train_model(
        make_proposal(),
        catalog,
        dataset,
        training_seed=7,
        dataloader_seed=8,
        device="cpu",
        max_training_seconds=30,
    )

    assert outcome.status is TrainingStatus.INVALID_CONFIG
    assert outcome.error_type == "ValueError"
