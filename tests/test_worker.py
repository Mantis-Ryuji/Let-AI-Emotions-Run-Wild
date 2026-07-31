from __future__ import annotations

from fizzbuzz_agent.agent_types import WorkerPrompt
from fizzbuzz_agent.config import ExperimentConfig
from fizzbuzz_agent.worker import LocalGemmaWorker, TransformersGemmaRuntime


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str]], dict[str, object], int]] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        generation_parameters: dict[str, object],
        *,
        seed: int,
    ) -> str:
        self.calls.append((messages, generation_parameters, seed))
        return "mock worker output"


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

