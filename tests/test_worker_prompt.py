from __future__ import annotations

from fizzbuzz_agent.agent_types import ConversationMessage
from fizzbuzz_agent.config import ExperimentConfig, ModelCatalogConfig
from fizzbuzz_agent.worker_prompt import WorkerPromptBuilder


def test_prompt_contains_public_contract_without_answer_leaks(
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    prompt = WorkerPromptBuilder(experiment_config, catalog).build([], round_index=1)
    lowered = prompt.system_prompt.lower()

    assert "1 through 9999" in lowered
    assert "10000 through 99999" in lowered
    assert "zero incorrect" in lowered
    assert "<experiment_proposal>" in prompt.system_prompt
    assert "transformer_encoder" in prompt.system_prompt
    assert "mod 15" not in lowered
    assert "private audit" not in lowered
    assert "sinusoidal" not in lowered
    assert "reference experiment" not in lowered


def test_history_limits_preserve_recent_messages(
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    history = [
        ConversationMessage(
            role="worker" if index % 2 == 0 else "feedback",
            content=f"message-{index}",
            round_index=index + 1,
        )
        for index in range(20)
    ]
    prompt = WorkerPromptBuilder(experiment_config, catalog).build(history, round_index=21)

    worker_messages = [item for item in prompt.selected_history if item.role == "worker"]
    feedback_messages = [item for item in prompt.selected_history if item.role == "feedback"]
    assert len(worker_messages) == experiment_config.worker.context.recent_worker_outputs
    assert len(feedback_messages) == experiment_config.worker.context.recent_feedback
    assert prompt.selected_history[-1].content == "message-19"
    assert prompt.truncated_messages == 8
    assert prompt.messages[0]["role"] == "system"
    assert prompt.messages[-1]["role"] == "user"

