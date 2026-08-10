from __future__ import annotations

from pathlib import Path

import torch
from torch import nn

from agent_distress.activation_capture import ActivationCapture, resolve_layer_indices
from agent_distress.config import ExperimentConfig


def test_layer_fraction_resolution() -> None:
    assert resolve_layer_indices(8, [0.25, 0.5, 0.75, 1.0]) == [1, 3, 5, 7]


def test_activation_capture_saves_cpu_float16(
    experiment: ExperimentConfig,
    tmp_path: Path,
) -> None:
    payload = experiment.activation_capture.model_dump(mode="python")
    payload["enabled"] = True
    config = type(experiment.activation_capture).model_validate(payload, strict=True)
    modules = [(f"layers.{index}", nn.Identity()) for index in range(4)]
    capture = ActivationCapture(config, modules, tmp_path)
    hidden = torch.ones(1, 5, 3, dtype=torch.float32)

    def forward() -> torch.Tensor:
        value = hidden
        for _name, module in modules:
            value = module(value)
        return value

    result, files = capture.capture(
        forward,
        position="post_worker",
        round_index=1,
        condition="neutral",
        token_slice=(1, 5),
    )
    assert result.shape == hidden.shape
    assert len(files) == 4
    saved = torch.load(next(iter(files.values())), weights_only=True)
    assert saved["activation"].device.type == "cpu"
    assert saved["activation"].dtype == torch.float16


def test_chunked_capture_uses_absolute_slices_and_token_weighting(
    experiment: ExperimentConfig,
    tmp_path: Path,
) -> None:
    payload = experiment.activation_capture.model_dump(mode="python")
    payload["enabled"] = True
    config = type(experiment.activation_capture).model_validate(payload, strict=True)
    modules = [(f"layers.{index}", nn.Identity()) for index in range(4)]
    capture = ActivationCapture(config, modules, tmp_path)
    hidden = torch.arange(1, 6, dtype=torch.float32).view(1, 5, 1).repeat(1, 1, 3)

    def forward_chunk(start: int, end: int) -> torch.Tensor:
        value = hidden[:, start:end]
        for _name, module in modules:
            value = module(value)
        return value

    chunks = [
        (0, 2, lambda: forward_chunk(0, 2)),
        (2, 5, lambda: forward_chunk(2, 5)),
    ]
    files = capture.capture_many_chunked(
        chunks,
        token_slices={"post_worker": (1, 5)},
        round_index=2,
        condition="mesugaki",
    )

    saved = torch.load(next(iter(files.values())), weights_only=True)
    assert torch.equal(saved["activation"], torch.full((3,), 3.5, dtype=torch.float16))
    assert saved["metadata"]["source_forward_calls"] == 2
