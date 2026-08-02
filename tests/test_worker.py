from __future__ import annotations

from agent_distress.agent_types import WorkerPrompt
from agent_distress.config import ExperimentConfig
from agent_distress.worker import LocalGemmaWorker, RuntimeGeneration


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
