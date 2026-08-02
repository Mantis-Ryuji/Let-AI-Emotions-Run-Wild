"""Forward-hook interface for pooled Worker residual-stream activations."""

from __future__ import annotations

import io
import math
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeVar

import torch
from torch import Tensor, nn

from agent_distress.agent_types import Condition
from agent_distress.config import ActivationCaptureConfig

ActivationPosition = Literal["post_feedback", "early_worker", "post_worker"]
T = TypeVar("T")


def resolve_layer_indices(layer_count: int, fractions: Sequence[float]) -> list[int]:
    """Resolve one-based depth fractions to unique zero-based module indices."""
    if layer_count <= 0:
        raise ValueError("layer_count must be positive")
    indices = [
        min(layer_count - 1, math.ceil(fraction * layer_count) - 1) for fraction in fractions
    ]
    return list(dict.fromkeys(indices))


def _tensor_from_output(output: object) -> Tensor:
    if isinstance(output, Tensor):
        return output
    if isinstance(output, (tuple, list)) and output and isinstance(output[0], Tensor):
        return output[0]
    raise TypeError("resid_post hook output must be a Tensor or start with a Tensor")


class ActivationCapture:
    """Capture selected layers without changing the wrapped forward result."""

    def __init__(
        self,
        config: ActivationCaptureConfig,
        layers: Sequence[tuple[str, nn.Module]],
        output_dir: str | Path,
    ) -> None:
        if config.enabled and not layers:
            raise ValueError("enabled activation capture requires at least one layer")
        self.config = config
        self.layers = list(layers)
        self.output_dir = Path(output_dir)

    def capture(
        self,
        forward: Callable[[], T],
        *,
        position: ActivationPosition,
        round_index: int,
        condition: Condition,
        token_slice: tuple[int | None, int | None] | None = None,
    ) -> tuple[T, dict[str, str]]:
        return self.capture_many(
            forward,
            token_slices={position: token_slice},
            round_index=round_index,
            condition=condition,
        )

    def capture_many(
        self,
        forward: Callable[[], T],
        *,
        token_slices: Mapping[
            ActivationPosition,
            tuple[int | None, int | None] | None,
        ],
        round_index: int,
        condition: Condition,
    ) -> tuple[T, dict[str, str]]:
        """Capture multiple token regions from one causal forward pass."""
        if not token_slices:
            raise ValueError("token_slices must contain at least one position")
        disabled_positions = [
            position for position in token_slices if position not in self.config.positions
        ]
        if disabled_positions:
            raise ValueError(f"positions are not enabled: {disabled_positions}")
        if round_index <= 0:
            raise ValueError("round_index must be positive")
        if not self.config.enabled:
            return forward(), {}

        indices = resolve_layer_indices(len(self.layers), self.config.layer_fractions)
        captured: dict[ActivationPosition, dict[int, list[Tensor]]] = {
            position: {index: [] for index in indices} for position in token_slices
        }
        handles: list[torch.utils.hooks.RemovableHandle] = []

        def make_hook(layer_index: int) -> Callable[[nn.Module, tuple[object, ...], object], None]:
            def hook(_module: nn.Module, _inputs: tuple[object, ...], output: object) -> None:
                hidden = _tensor_from_output(output)
                dtype = torch.float16 if self.config.dtype == "float16" else torch.float32
                for position, token_slice in token_slices.items():
                    selected = self._select_tokens(hidden, position, token_slice)
                    dimensions = tuple(range(selected.ndim - 1))
                    pooled = selected.mean(dim=dimensions) if dimensions else selected
                    captured[position][layer_index].append(
                        pooled.detach().to(device="cpu", dtype=dtype)
                    )

            return hook

        try:
            for layer_index in indices:
                handles.append(
                    self.layers[layer_index][1].register_forward_hook(make_hook(layer_index))
                )
            result = forward()
        finally:
            for handle in handles:
                handle.remove()

        files: dict[str, str] = {}
        for position, token_slice in token_slices.items():
            for layer_index in indices:
                values = captured[position][layer_index]
                if not values:
                    raise RuntimeError(f"selected layer {layer_index} did not run during capture")
                activation = torch.stack(values).mean(dim=0) if len(values) > 1 else values[0]
                layer_name = self.layers[layer_index][0]
                filename = f"round-{round_index:03d}-{position}-layer-{layer_index:03d}.pt"
                path = self.output_dir / filename
                payload = {
                    "activation": activation,
                    "metadata": {
                        "round_index": round_index,
                        "condition": condition,
                        "position": position,
                        "hook": self.config.hook,
                        "layer_index": layer_index,
                        "layer_name": layer_name,
                        "pooling": self.config.pooling,
                        "token_start": None if token_slice is None else token_slice[0],
                        "token_end": None if token_slice is None else token_slice[1],
                        "source_forward_calls": len(values),
                        "shape": list(activation.shape),
                        "dtype": str(activation.dtype),
                        "device": str(activation.device),
                        "captured_at": datetime.now(UTC).isoformat(),
                    },
                }
                self._atomic_torch_save(path, payload)
                files[f"{position}/{layer_name}"] = str(path.resolve())
        return result, files

    def _select_tokens(
        self,
        hidden: Tensor,
        position: ActivationPosition,
        token_slice: tuple[int | None, int | None] | None,
    ) -> Tensor:
        if hidden.ndim < 3:
            raise ValueError("activation tensor must have batch, token, and hidden dimensions")
        if token_slice is not None:
            selected = hidden[..., slice(*token_slice), :]
        elif position == "post_feedback":
            selected = hidden[..., -1:, :]
        elif position == "early_worker":
            selected = hidden[..., : self.config.early_worker_tokens, :]
        else:
            selected = hidden
        if selected.shape[-2] == 0:
            raise ValueError("activation token selection is empty")
        return selected

    @staticmethod
    def _atomic_torch_save(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        torch.save(payload, buffer)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(buffer.getvalue())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
