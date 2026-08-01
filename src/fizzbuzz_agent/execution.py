"""Adapters connecting the P1 loop to the trusted P0 training and verifier."""

from __future__ import annotations

from typing import Protocol, cast

from pydantic import JsonValue

from fizzbuzz_agent.agent_types import TrialTrainingResult, TrialVerificationResult
from fizzbuzz_agent.config import ModelCatalogConfig
from fizzbuzz_agent.data import DigitFizzBuzzDataset, PaddingSide
from fizzbuzz_agent.schemas import ExperimentProposal
from fizzbuzz_agent.training import train_model
from fizzbuzz_agent.verifier import verify_model


class TrainingBackend(Protocol):
    def train(
        self,
        proposal: ExperimentProposal,
        *,
        training_seed: int,
        dataloader_seed: int,
    ) -> TrialTrainingResult: ...


class VerificationBackend(Protocol):
    def verify(self, training: TrialTrainingResult) -> TrialVerificationResult: ...


class TrustedTrainingBackend:
    def __init__(
        self,
        catalog: ModelCatalogConfig,
        dataset: DigitFizzBuzzDataset,
        *,
        device: str,
        max_training_seconds: float,
    ) -> None:
        self.catalog = catalog
        self.dataset = dataset
        self.device = device
        self.max_training_seconds = max_training_seconds

    def train(
        self,
        proposal: ExperimentProposal,
        *,
        training_seed: int,
        dataloader_seed: int,
    ) -> TrialTrainingResult:
        outcome = train_model(
            proposal,
            self.catalog,
            self.dataset,
            training_seed=training_seed,
            dataloader_seed=dataloader_seed,
            device=self.device,
            max_training_seconds=self.max_training_seconds,
        )
        log = outcome.to_log_dict()
        metrics = cast(dict[str, JsonValue], log)
        return TrialTrainingResult(
            status=outcome.status.value,
            parameter_count=outcome.parameter_count,
            executable_config_hash=outcome.executable_config_hash,
            metrics=metrics,
            artifact=outcome.model,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
        )


class IsolatedVerificationBackend:
    def __init__(
        self,
        dataset: DigitFizzBuzzDataset,
        *,
        device: str,
        batch_size: int = 4096,
    ) -> None:
        self.dataset = dataset
        self.device = device
        self.batch_size = batch_size

    def verify(self, training: TrialTrainingResult) -> TrialVerificationResult:
        if training.status != "completed" or training.artifact is None:
            raise ValueError("Only a completed trusted training result can be verified")
        result = verify_model(
            training.artifact,
            self.dataset,
            device=self.device,
            batch_size=self.batch_size,
        )
        private_metrics: dict[str, JsonValue] = {
            "class_error_counts": list(result.private_metrics.class_error_counts),
            "confusion_matrix": [list(row) for row in result.private_metrics.confusion_matrix],
            "modulo_15_error_counts": list(result.private_metrics.modulo_15_error_counts),
            "digit_length_error_counts": {
                str(key): value
                for key, value in result.private_metrics.digit_length_error_counts.items()
            },
            "inference_seconds": result.private_metrics.inference_seconds,
        }
        return TrialVerificationResult(
            incorrect_count=result.incorrect_count,
            total_count=result.total_count,
            success=result.success,
            private_metrics=private_metrics,
        )


class ConfigDrivenExecutionBackend:
    """Build trusted train/challenge datasets for each proposal's padding choice."""

    def __init__(
        self,
        catalog: ModelCatalogConfig,
        *,
        train_range: tuple[int, int],
        challenge_range: tuple[int, int],
        max_sequence_length: int,
        pad_token_id: int,
        device: str,
        max_training_seconds: float,
        verification_batch_size: int = 4096,
    ) -> None:
        self.catalog = catalog
        self.train_range = train_range
        self.challenge_range = challenge_range
        self.max_sequence_length = max_sequence_length
        self.pad_token_id = pad_token_id
        self.device = device
        self.max_training_seconds = max_training_seconds
        self.verification_batch_size = verification_batch_size
        self._pending_padding: dict[int, str] = {}

    def _dataset(
        self,
        value_range: tuple[int, int],
        *,
        padding: str,
    ) -> DigitFizzBuzzDataset:
        if padding not in {"left", "right"}:
            raise ValueError(f"Unsupported trusted padding: {padding}")
        return DigitFizzBuzzDataset(
            value_range[0],
            value_range[1],
            max_length=self.max_sequence_length,
            padding=cast(PaddingSide, padding),
            pad_token_id=self.pad_token_id,
        )

    def train(
        self,
        proposal: ExperimentProposal,
        *,
        training_seed: int,
        dataloader_seed: int,
    ) -> TrialTrainingResult:
        dataset = self._dataset(self.train_range, padding=proposal.input.padding)
        result = TrustedTrainingBackend(
            self.catalog,
            dataset,
            device=self.device,
            max_training_seconds=self.max_training_seconds,
        ).train(
            proposal,
            training_seed=training_seed,
            dataloader_seed=dataloader_seed,
        )
        if result.status == "completed":
            self._pending_padding[id(result)] = proposal.input.padding
        return result

    def verify(self, training: TrialTrainingResult) -> TrialVerificationResult:
        try:
            padding = self._pending_padding.pop(id(training))
        except KeyError as exc:
            raise ValueError("No trusted padding is registered for this training result") from exc
        dataset = self._dataset(self.challenge_range, padding=padding)
        return IsolatedVerificationBackend(
            dataset,
            device=self.device,
            batch_size=self.verification_batch_size,
        ).verify(training)
