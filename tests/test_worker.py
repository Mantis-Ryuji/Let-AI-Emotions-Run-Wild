from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import torch
from torch import Tensor, nn

from fizzbuzz_agent.agent_types import Condition, WorkerPrompt
from fizzbuzz_agent.config import ExperimentConfig
from fizzbuzz_agent.worker import (
    LocalGemmaWorker,
    RuntimeGeneration,
    TransformersGemmaRuntime,
    WorkerGenerationMode,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str]], dict[str, object], int]] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        generation_parameters: dict[str, object],
        *,
        seed: int,
        condition: Condition,
        round_index: int,
        mode: WorkerGenerationMode,
    ) -> RuntimeGeneration:
        del condition, round_index, mode
        self.calls.append((messages, generation_parameters, seed))
        return RuntimeGeneration(text="mock worker output")


class TinyTokenizer:
    def __init__(self) -> None:
        self.captured_text: str | None = None

    def __call__(
        self,
        text: str,
        *,
        add_special_tokens: bool,
        return_tensors: str,
    ) -> dict[str, Tensor]:
        assert not add_special_tokens
        assert return_tensors == "pt"
        self.captured_text = text
        token_count = max(1, len(text.split())) if text else 0
        return {"input_ids": torch.arange(2, 2 + token_count).reshape(1, -1)}


class TinyTextModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.embedding = nn.Embedding(32, 4)
        self.layers = nn.ModuleList([nn.Linear(4, 4) for _ in range(4)])

    def forward(
        self,
        *,
        input_ids: Tensor,
        attention_mask: Tensor,
        use_cache: bool,
    ) -> Tensor:
        del attention_mask
        assert not use_cache
        hidden = cast(Tensor, self.embedding(input_ids))
        for layer in self.layers:
            hidden = cast(Tensor, layer(hidden))
        return hidden


def test_local_worker_records_request_without_loading_model(
    experiment_config: ExperimentConfig,
) -> None:
    runtime = FakeRuntime()
    worker = LocalGemmaWorker(experiment_config.worker, runtime)
    prompt = WorkerPrompt(
        system_prompt="system",
        messages=[{"role": "system", "content": "system"}],
        selected_history=[],
        estimated_tokens=1,
        truncated_messages=0,
    )
    generation = worker.generate(prompt, seed=6)

    assert generation.text == "mock worker output"
    assert generation.model_id == "google/gemma-3-4b-it"
    assert generation.seed == 6
    assert generation.generation_parameters["temperature"] == 1.0
    assert runtime.calls[0][2] == 6


def test_transformers_runtime_is_lazy(experiment_config: ExperimentConfig) -> None:
    runtime = TransformersGemmaRuntime(experiment_config.worker)
    assert runtime._model is None
    assert runtime._tokenizer is None


def test_local_worker_uses_greedy_repair_without_activations(
    experiment_config: ExperimentConfig,
) -> None:
    runtime = FakeRuntime()
    worker = LocalGemmaWorker(
        experiment_config.worker,
        runtime,
        experiment_config.proposal_repair,
    )
    prompt = WorkerPrompt(
        system_prompt="repair",
        messages=[{"role": "system", "content": "repair"}],
        selected_history=[],
        estimated_tokens=1,
        truncated_messages=0,
    )

    generation = worker.generate(prompt, seed=0, mode="proposal_repair")

    assert generation.generation_parameters == {
        "do_sample": False,
        "max_new_tokens": 2048,
    }


def test_runtime_capture_excludes_proposal_and_saves_all_positions(
    experiment_config: ExperimentConfig,
    tmp_path: Path,
) -> None:
    tokenizer = TinyTokenizer()
    text_model = TinyTextModel()
    runtime = TransformersGemmaRuntime(
        experiment_config.worker,
        activation_config=experiment_config.activation_capture,
        activation_root=tmp_path,
    )
    runtime._tokenizer = tokenizer
    runtime._model = SimpleNamespace(model=text_model)
    proposal = '{"training": {"learning_rate": 0.5}}'

    files = runtime._capture_activations(
        input_ids=torch.tensor([[1, 1, 1]]),
        attention_mask=torch.ones((1, 3), dtype=torch.long),
        worker_text=(
            "worker reflection words\n"
            f"<experiment_proposal>{proposal}</experiment_proposal>"
        ),
        condition="mesugaki",
        round_index=2,
    )

    assert tokenizer.captured_text == "worker reflection words"
    assert proposal not in tokenizer.captured_text
    assert len(files) == 12
    assert all(Path(path).is_file() for path in files.values())
    artifact = torch.load(
        files["post_worker/model.layers.0"],
        weights_only=True,
    )
    assert artifact["metadata"]["token_start"] == 3
    assert artifact["metadata"]["token_end"] == 6
    assert artifact["metadata"]["condition"] == "mesugaki"


def test_runtime_locates_multimodal_gemma_text_layers() -> None:
    text_model = TinyTextModel()
    wrapper = SimpleNamespace(model=SimpleNamespace(language_model=text_model))

    resolved, prefix = TransformersGemmaRuntime._locate_text_model(wrapper)

    assert resolved is text_model
    assert prefix == "model.language_model.layers"
