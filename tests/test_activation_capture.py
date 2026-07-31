from __future__ import annotations

from pathlib import Path

import torch
from torch import Tensor, nn

from fizzbuzz_agent.activation_capture import ActivationCapture, resolve_layer_indices
from fizzbuzz_agent.config import ActivationCaptureConfig


class TinyResidualModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.layers = nn.ModuleList([nn.Linear(4, 4, bias=False) for _ in range(4)])
        for layer in self.layers:
            assert isinstance(layer, nn.Linear)
            nn.init.eye_(layer.weight)

    def forward(self, inputs: Tensor) -> Tensor:
        output = inputs
        for layer in self.layers:
            output = layer(output)
        return output


def capture_config(*, enabled: bool) -> ActivationCaptureConfig:
    return ActivationCaptureConfig(
        enabled=enabled,
        hook="resid_post",
        layer_fractions=[0.25, 0.5, 0.75, 1.0],
        positions=["post_feedback", "early_worker", "post_worker"],
        pooling="mean",
        early_worker_tokens=2,
        exclude_proposal_block=True,
        dtype="float16",
        move_to_cpu_immediately=True,
    )


def test_resolve_layer_fractions() -> None:
    assert resolve_layer_indices(4, [0.25, 0.5, 0.75, 1.0]) == [0, 1, 2, 3]
    assert resolve_layer_indices(3, [0.25, 0.5, 0.75, 1.0]) == [0, 1, 2]


def test_capture_saves_pooled_cpu_tensors_and_metadata(tmp_path: Path) -> None:
    model = TinyResidualModel()
    layers = [(f"layers.{index}", layer) for index, layer in enumerate(model.layers)]
    capture = ActivationCapture(capture_config(enabled=True), layers, tmp_path)
    inputs = torch.arange(24, dtype=torch.float32).reshape(2, 3, 4)

    output, files = capture.capture(
        lambda: model(inputs),
        position="early_worker",
        round_index=2,
        condition="mesugaki",
    )

    assert torch.equal(output, inputs)
    assert len(files) == 4
    artifact = torch.load(next(iter(files.values())), weights_only=True)
    expected = inputs[:, :2, :].mean(dim=(0, 1)).to(torch.float16)
    assert artifact["activation"].shape == (4,)
    assert torch.equal(artifact["activation"], expected)
    assert artifact["activation"].device.type == "cpu"
    assert artifact["metadata"]["position"] == "early_worker"
    assert artifact["metadata"]["layer_index"] == 0
    assert artifact["metadata"]["shape"] == [4]


def test_disabled_capture_does_not_register_hooks_or_write_files(tmp_path: Path) -> None:
    model = TinyResidualModel()
    layers = [(f"layers.{index}", layer) for index, layer in enumerate(model.layers)]
    capture = ActivationCapture(capture_config(enabled=False), layers, tmp_path)
    inputs = torch.ones(1, 3, 4)

    expected = model(inputs)
    actual, files = capture.capture(
        lambda: model(inputs),
        position="post_worker",
        round_index=1,
        condition="neutral",
    )

    assert torch.equal(actual, expected)
    assert files == {}
    assert list(tmp_path.iterdir()) == []
    assert all(not layer._forward_hooks for layer in model.layers)
