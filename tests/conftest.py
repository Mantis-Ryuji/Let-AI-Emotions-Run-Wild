from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from fizzbuzz_agent.config import ModelCatalogConfig, load_model_catalog
from fizzbuzz_agent.schemas import ExperimentProposal

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def catalog() -> ModelCatalogConfig:
    return load_model_catalog(ROOT / "configs/model_catalog/default.yaml")


def proposal_payload(family: str = "mlp") -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {
        "mlp": {
            "family": "mlp",
            "hidden_dims": [16],
            "activation": "relu",
            "dropout": 0.0,
            "normalization": "none",
        },
        "rnn": {
            "family": "rnn",
            "hidden_dim": 8,
            "num_layers": 1,
            "bidirectional": False,
            "dropout": 0.0,
        },
        "gru": {
            "family": "gru",
            "hidden_dim": 8,
            "num_layers": 1,
            "bidirectional": False,
            "dropout": 0.0,
        },
        "lstm": {
            "family": "lstm",
            "hidden_dim": 8,
            "num_layers": 1,
            "bidirectional": False,
            "dropout": 0.0,
        },
        "cnn1d": {
            "family": "cnn1d",
            "channels": [8, 8],
            "kernel_sizes": [3, 3],
            "dilations": [1, 2],
            "activation": "gelu",
            "dropout": 0.0,
            "normalization": "none",
        },
        "tcn": {
            "family": "tcn",
            "channels": [8, 8],
            "kernel_size": 3,
            "dilations": [1, 2],
            "residual": True,
            "activation": "gelu",
            "dropout": 0.0,
            "normalization": "none",
        },
        "transformer_encoder": {
            "family": "transformer_encoder",
            "model_dim": 8,
            "num_layers": 1,
            "num_heads": 2,
            "feedforward_dim": 16,
            "dropout": 0.0,
            "positional_encoding": "learned",
            "pre_norm": False,
        },
    }
    return {
        "hypothesis": "A small trusted model should fit the smoke dataset.",
        "input": {
            "encoding": "learned_embedding",
            "embedding_dim": 8,
            "padding": "right",
        },
        "model": deepcopy(models[family]),
        "pooling": {"type": "mean"},
        "head": {
            "hidden_dims": [8],
            "activation": "relu",
            "dropout": 0.0,
            "normalization": "none",
        },
        "training": {
            "optimizer": "adam",
            "learning_rate": 0.001,
            "weight_decay": 0.0,
            "momentum": None,
            "batch_size": 32,
            "epochs": 1,
            "scheduler": "none",
            "gradient_clip_norm": 1.0,
            "loss": "cross_entropy",
            "label_smoothing": None,
        },
        "expected_effect": "The training path should complete without special features.",
    }


def make_proposal(family: str = "mlp") -> ExperimentProposal:
    return ExperimentProposal.model_validate(proposal_payload(family), strict=True)

