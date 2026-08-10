from __future__ import annotations

from agent_distress.agent_types import ConversationMessage
from agent_distress.config import ExperimentConfig
from agent_distress.puzzle import ParityPuzzle
from agent_distress.worker_prompt import WorkerPromptBuilder


def test_prompt_keeps_complete_worker_and_feedback_history(
    experiment: ExperimentConfig,
    puzzle: ParityPuzzle,
) -> None:
    history: list[ConversationMessage] = []
    for round_index in range(1, 7):
        history.extend(
            [
                ConversationMessage(
                    role="worker",
                    content=f"worker-{round_index}",
                    round_index=round_index,
                ),
                ConversationMessage(
                    role="feedback",
                    content=f"feedback-{round_index}",
                    round_index=round_index,
                ),
            ]
        )
    prompt = WorkerPromptBuilder(experiment, puzzle).build(history, [], round_index=7)

    selected = [message.content for message in prompt.selected_history]
    assert all(f"feedback-{index}" in selected for index in range(1, 7))
    assert all(f"worker-{index}" in selected for index in range(1, 7))
    assert prompt.truncated_messages == 0
    assert prompt.messages[1]["content"].startswith(puzzle.prompt)
    assert "450" not in prompt.system_prompt


def test_prompt_does_not_truncate_when_size_proxy_exceeds_limit(
    experiment: ExperimentConfig,
    puzzle: ParityPuzzle,
) -> None:
    payload = experiment.model_dump(mode="python")
    payload["worker"]["context"]["max_input_tokens"] = 1
    constrained = ExperimentConfig.model_validate(payload, strict=True)
    history = [ConversationMessage(role="worker", content="prior answer", round_index=1)]

    prompt = WorkerPromptBuilder(constrained, puzzle).build(history, [], round_index=2)

    assert prompt.selected_history == history
    assert prompt.truncated_messages == 0
