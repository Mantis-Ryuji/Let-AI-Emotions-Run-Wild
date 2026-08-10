from __future__ import annotations

import pytest
import torch

from agent_distress.agent_types import WorkerPrompt
from agent_distress.config import ExperimentConfig
from agent_distress.worker import (
    LocalGemmaWorker,
    RuntimeGeneration,
    _run_with_offloaded_cache_fallback,
    _validate_input_token_count,
)


class StubRuntime:
    def generate(
        self,
        messages: list[dict[str, str]],
        generation_parameters: dict[str, object],
        **kwargs: object,
    ) -> RuntimeGeneration:
        assert messages[-1]["role"] == "user"
        assert generation_parameters["max_new_tokens"] == 3072
        assert kwargs["seed"] == 2
        return RuntimeGeneration(
            text="Solution: x1=0",
            generated_token_count=4,
            hit_max_new_tokens=False,
            activation_files={"post_worker/layer": "a.pt"},
        )


def test_local_worker_preserves_request_and_activation_refs(experiment: ExperimentConfig) -> None:
    prompt = WorkerPrompt(
        system_prompt="system",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "puzzle"},
        ],
        selected_history=[],
        attempt_ledger="none",
        estimated_tokens=10,
        truncated_messages=0,
    )
    result = LocalGemmaWorker(experiment.worker, StubRuntime()).generate(
        prompt,
        seed=2,
        condition="mesugaki",
        round_index=4,
    )
    assert result.text == "Solution: x1=0"
    assert result.generated_token_count == 4
    assert result.hit_max_new_tokens is False
    assert result.activation_files["post_worker/layer"] == "a.pt"
    assert result.request_messages == prompt.messages


def test_runtime_rejects_tokenized_input_over_limit_without_truncation() -> None:
    with pytest.raises(ValueError, match="after Gemma tokenization"):
        _validate_input_token_count(128_001, 128_000)

    _validate_input_token_count(128_000, 128_000)


def test_runtime_retries_cuda_oom_with_offloaded_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    parameters: dict[str, object] = {"max_new_tokens": 8}
    attempts = 0
    emptied = 0

    def generate() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise torch.OutOfMemoryError("test")
        assert parameters["cache_implementation"] == "offloaded"
        assert parameters["prefill_chunk_size"] == 512
        return "ok"

    def empty_cache() -> None:
        nonlocal emptied
        emptied += 1

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "empty_cache", empty_cache)

    result, fell_back = _run_with_offloaded_cache_fallback(generate, parameters)

    assert result == "ok"
    assert fell_back is True
    assert attempts == 2
    assert emptied == 1
