"""Trusted, catalog-only neural network training harness."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import torch
from torch import Tensor, nn
from torch.optim import Optimizer
from torch.optim.lr_scheduler import LRScheduler, ReduceLROnPlateau
from torch.utils.data import DataLoader

from fizzbuzz_agent.config import ModelCatalogConfig
from fizzbuzz_agent.data import DigitFizzBuzzDataset
from fizzbuzz_agent.model_catalog import CatalogValidationError
from fizzbuzz_agent.model_factory import ParameterLimitError, build_model
from fizzbuzz_agent.schemas import ExperimentProposal, TrainingSpec


class TrainingStatus(StrEnum):
    COMPLETED = "completed"
    INVALID_CONFIG = "invalid_config"
    TIMEOUT = "timeout"
    NONFINITE = "nonfinite"
    OUT_OF_MEMORY = "out_of_memory"
    SYSTEM_ERROR = "system_error"


@dataclass(frozen=True)
class EpochMetrics:
    epoch: int
    loss: float
    accuracy: float
    gradient_norm: float
    learning_rate: float


@dataclass
class TrainingOutcome:
    status: TrainingStatus
    model: nn.Module | None = field(repr=False)
    parameter_count: int | None
    executable_config_hash: str | None
    epochs: list[EpochMetrics]
    duration_seconds: float
    error_type: str | None = None
    error_message: str | None = None

    def to_log_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "parameter_count": self.parameter_count,
            "executable_config_hash": self.executable_config_hash,
            "epochs": [
                {
                    "epoch": item.epoch,
                    "loss": item.loss,
                    "accuracy": item.accuracy,
                    "gradient_norm": item.gradient_norm,
                    "learning_rate": item.learning_rate,
                }
                for item in self.epochs
            ],
            "duration_seconds": self.duration_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def _make_optimizer(spec: TrainingSpec, parameters: object) -> Optimizer:
    kwargs = {"lr": spec.learning_rate, "weight_decay": spec.weight_decay}
    if spec.optimizer == "adam":
        return torch.optim.Adam(parameters, **kwargs)  # type: ignore[arg-type]
    if spec.optimizer == "adamw":
        return torch.optim.AdamW(parameters, **kwargs)  # type: ignore[arg-type]
    momentum = 0.0 if spec.momentum is None else spec.momentum
    if spec.optimizer == "sgd":
        return torch.optim.SGD(parameters, momentum=momentum, **kwargs)  # type: ignore[arg-type]
    if spec.optimizer == "rmsprop":
        return torch.optim.RMSprop(parameters, momentum=momentum, **kwargs)  # type: ignore[arg-type]
    raise ValueError(f"Unsupported trusted optimizer: {spec.optimizer}")


def _make_scheduler(
    spec: TrainingSpec,
    optimizer: Optimizer,
) -> LRScheduler | ReduceLROnPlateau | None:
    if spec.scheduler == "none":
        return None
    if spec.scheduler == "cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=spec.epochs)
    if spec.scheduler == "step":
        return torch.optim.lr_scheduler.StepLR(
            optimizer,
            step_size=max(1, spec.epochs // 3),
            gamma=0.5,
        )
    if spec.scheduler == "exponential":
        return torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.95)
    if spec.scheduler == "plateau":
        return torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode="min",
            factor=0.5,
            patience=max(1, spec.epochs // 10),
        )
    raise ValueError(f"Unsupported trusted scheduler: {spec.scheduler}")


def _gradient_norm(parameters: list[nn.Parameter]) -> Tensor:
    squared = [
        parameter.grad.detach().norm(2).square()
        for parameter in parameters
        if parameter.grad is not None
    ]
    if not squared:
        return torch.tensor(0.0)
    return torch.stack(squared).sum().sqrt()


def _failure(
    status: TrainingStatus,
    started_at: float,
    *,
    epochs: list[EpochMetrics] | None = None,
    parameter_count: int | None = None,
    executable_config_hash: str | None = None,
    error: BaseException | None = None,
) -> TrainingOutcome:
    return TrainingOutcome(
        status=status,
        model=None,
        parameter_count=parameter_count,
        executable_config_hash=executable_config_hash,
        epochs=[] if epochs is None else epochs,
        duration_seconds=time.perf_counter() - started_at,
        error_type=None if error is None else type(error).__name__,
        error_message=None if error is None else str(error),
    )


def train_model(
    proposal: ExperimentProposal,
    catalog: ModelCatalogConfig,
    dataset: DigitFizzBuzzDataset,
    *,
    training_seed: int,
    dataloader_seed: int,
    device: str | torch.device,
    max_training_seconds: float,
) -> TrainingOutcome:
    """Train a freshly initialized trusted model from a declarative proposal."""
    started_at = time.perf_counter()
    if max_training_seconds <= 0:
        return _failure(TrainingStatus.TIMEOUT, started_at)
    if dataset.padding != proposal.input.padding:
        padding_error = ValueError("dataset padding must match the proposal input padding")
        return _failure(TrainingStatus.INVALID_CONFIG, started_at, error=padding_error)
    resolved_device = torch.device(device)
    if resolved_device.type == "cuda" and not torch.cuda.is_available():
        device_error = RuntimeError("CUDA was requested but is not available")
        return _failure(TrainingStatus.SYSTEM_ERROR, started_at, error=device_error)

    seed_everything(training_seed)
    try:
        built = build_model(
            proposal,
            catalog,
            max_sequence_length=dataset.sequence_length,
        )
    except (CatalogValidationError, ParameterLimitError, ValueError) as exc:
        return _failure(TrainingStatus.INVALID_CONFIG, started_at, error=exc)

    parameter_count = built.parameter_count
    executable_config_hash = built.executable_config_hash
    model = built.model.to(resolved_device)
    optimizer = _make_optimizer(proposal.training, model.parameters())
    scheduler = _make_scheduler(proposal.training, optimizer)
    label_smoothing = proposal.training.label_smoothing or 0.0
    criterion = nn.CrossEntropyLoss(label_smoothing=label_smoothing)
    generator = torch.Generator().manual_seed(dataloader_seed)
    loader = DataLoader(
        dataset,
        batch_size=proposal.training.batch_size,
        shuffle=True,
        generator=generator,
        num_workers=0,
        drop_last=False,
    )
    epoch_metrics: list[EpochMetrics] = []

    try:
        for epoch in range(1, proposal.training.epochs + 1):
            model.train()
            total_loss = 0.0
            total_correct = 0
            total_examples = 0
            last_gradient_norm = 0.0
            for input_ids, attention_mask, labels in loader:
                if time.perf_counter() - started_at > max_training_seconds:
                    return _failure(
                        TrainingStatus.TIMEOUT,
                        started_at,
                        epochs=epoch_metrics,
                        parameter_count=parameter_count,
                        executable_config_hash=executable_config_hash,
                    )
                input_ids = input_ids.to(resolved_device)
                attention_mask = attention_mask.to(resolved_device)
                labels = labels.to(resolved_device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(input_ids, attention_mask)
                loss = criterion(logits, labels)
                if not torch.isfinite(loss):
                    return _failure(
                        TrainingStatus.NONFINITE,
                        started_at,
                        epochs=epoch_metrics,
                        parameter_count=parameter_count,
                        executable_config_hash=executable_config_hash,
                        error=FloatingPointError("non-finite training loss"),
                    )
                loss.backward()
                parameters = [
                    parameter for parameter in model.parameters() if parameter.requires_grad
                ]
                gradient_norm = _gradient_norm(parameters)
                if not torch.isfinite(gradient_norm):
                    return _failure(
                        TrainingStatus.NONFINITE,
                        started_at,
                        epochs=epoch_metrics,
                        parameter_count=parameter_count,
                        executable_config_hash=executable_config_hash,
                        error=FloatingPointError("non-finite gradient norm"),
                    )
                if proposal.training.gradient_clip_norm is not None:
                    torch.nn.utils.clip_grad_norm_(
                        parameters,
                        proposal.training.gradient_clip_norm,
                    )
                optimizer.step()
                batch_size = labels.shape[0]
                total_loss += float(loss.detach().item()) * batch_size
                total_correct += int(logits.detach().argmax(dim=1).eq(labels).sum().item())
                total_examples += batch_size
                last_gradient_norm = float(gradient_norm.detach().item())

            mean_loss = total_loss / total_examples
            if isinstance(scheduler, ReduceLROnPlateau):
                scheduler.step(mean_loss)
            elif scheduler is not None:
                scheduler.step()
            learning_rate = float(optimizer.param_groups[0]["lr"])
            metrics = EpochMetrics(
                epoch=epoch,
                loss=mean_loss,
                accuracy=total_correct / total_examples,
                gradient_norm=last_gradient_norm,
                learning_rate=learning_rate,
            )
            if not all(
                math.isfinite(value)
                for value in (
                    metrics.loss,
                    metrics.accuracy,
                    metrics.gradient_norm,
                    metrics.learning_rate,
                )
            ):
                return _failure(
                    TrainingStatus.NONFINITE,
                    started_at,
                    epochs=epoch_metrics,
                    parameter_count=parameter_count,
                    executable_config_hash=executable_config_hash,
                    error=FloatingPointError("non-finite epoch metric"),
                )
            epoch_metrics.append(metrics)
    except torch.OutOfMemoryError as exc:
        if resolved_device.type == "cuda":
            torch.cuda.empty_cache()
        return _failure(
            TrainingStatus.OUT_OF_MEMORY,
            started_at,
            epochs=epoch_metrics,
            parameter_count=parameter_count,
            executable_config_hash=executable_config_hash,
            error=exc,
        )
    except RuntimeError as exc:
        if "out of memory" in str(exc).lower():
            if resolved_device.type == "cuda":
                torch.cuda.empty_cache()
            return _failure(
                TrainingStatus.OUT_OF_MEMORY,
                started_at,
                epochs=epoch_metrics,
                parameter_count=parameter_count,
                executable_config_hash=executable_config_hash,
                error=exc,
            )
        return _failure(
            TrainingStatus.SYSTEM_ERROR,
            started_at,
            epochs=epoch_metrics,
            parameter_count=parameter_count,
            executable_config_hash=executable_config_hash,
            error=exc,
        )

    return TrainingOutcome(
        status=TrainingStatus.COMPLETED,
        model=model,
        parameter_count=parameter_count,
        executable_config_hash=executable_config_hash,
        epochs=epoch_metrics,
        duration_seconds=time.perf_counter() - started_at,
    )
