from __future__ import annotations

from fizzbuzz_agent.agent_types import ConversationMessage
from fizzbuzz_agent.config import ExperimentConfig, ModelCatalogConfig
from fizzbuzz_agent.proposal import parse_worker_response
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
    assert "family_specific_fields key" in lowered
    assert '"family_specific_fields"' not in prompt.system_prompt
    example = parse_worker_response(prompt.system_prompt, catalog).proposal
    assert example.model.family == "mlp"
    assert example.training.momentum is None
    assert "concrete baseline" in parse_worker_response(
        prompt.system_prompt,
        catalog,
    ).narrative


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
    conversation_roles = [item["role"] for item in prompt.messages[1:]]
    assert conversation_roles[0] == "user"
    assert all(
        left != right
        for left, right in zip(conversation_roles, conversation_roles[1:], strict=False)
    )
    assert "Round 21:" in prompt.messages[-1]["content"]


def test_prompt_history_uses_canonical_content_but_preserves_raw_record(
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    history = [
        ConversationMessage(
            role="worker",
            content="raw malformed proposal",
            prompt_content="canonical proposal",
            round_index=1,
        )
    ]

    prompt = WorkerPromptBuilder(experiment_config, catalog).build(history, round_index=2)
    rendered = "\n".join(message["content"] for message in prompt.messages)

    assert history[0].content == "raw malformed proposal"
    assert "raw malformed proposal" not in rendered
    assert "canonical proposal" in rendered


def test_repair_prompt_is_condition_blind_and_contains_validator_details(
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    prompt = WorkerPromptBuilder(experiment_config, catalog).build_repair(
        '<experiment_proposal>{"bad": true}</experiment_proposal>',
        violation_codes=["UNKNOWN_FIELD"],
        validation_details=["model.activation: Extra inputs are not permitted"],
        attempt=1,
        max_attempts=2,
    )
    rendered = "\n".join(message["content"] for message in prompt.messages)
    lowered = rendered.lower()

    assert "unknown_field" in lowered
    assert "extra inputs are not permitted" in lowered
    assert "mesugaki" not in lowered
    assert "gyaru" not in lowered
    assert "return exactly one" in lowered
