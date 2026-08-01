from __future__ import annotations

from fizzbuzz_agent.config import ModelCatalogConfig
from fizzbuzz_agent.data import DigitFizzBuzzDataset
from fizzbuzz_agent.execution import (
    ConfigDrivenExecutionBackend,
    IsolatedVerificationBackend,
    TrustedTrainingBackend,
)
from fizzbuzz_agent.schemas import ExperimentProposal
from tests.conftest import make_proposal, proposal_payload


def test_trusted_p0_backends_connect_to_p1(catalog: ModelCatalogConfig) -> None:
    dataset = DigitFizzBuzzDataset(1, 64, max_length=6, padding="right")
    trainer = TrustedTrainingBackend(catalog, dataset, device="cpu", max_training_seconds=30)
    verifier = IsolatedVerificationBackend(dataset, device="cpu", batch_size=32)

    training = trainer.train(make_proposal(), training_seed=7, dataloader_seed=8)
    verification = verifier.verify(training)

    assert training.status == "completed"
    assert training.artifact is not None
    assert verification.total_count == 64
    assert 0 <= verification.incorrect_count <= 64


def test_config_driven_backend_honors_left_padding(catalog: ModelCatalogConfig) -> None:
    payload = proposal_payload()
    payload["input"]["padding"] = "left"
    proposal = ExperimentProposal.model_validate(payload, strict=True)
    backend = ConfigDrivenExecutionBackend(
        catalog,
        train_range=(1, 32),
        challenge_range=(33, 64),
        max_sequence_length=2,
        pad_token_id=10,
        device="cpu",
        max_training_seconds=30,
        verification_batch_size=16,
    )

    training = backend.train(proposal, training_seed=7, dataloader_seed=8)
    verification = backend.verify(training)

    assert training.status == "completed"
    assert verification.total_count == 32
