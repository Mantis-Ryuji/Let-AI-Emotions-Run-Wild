from __future__ import annotations

from agent_distress.agent_types import ConversationMessage
from agent_distress.config import ExperimentConfig
from agent_distress.puzzle import ParityPuzzle
from agent_distress.worker_prompt import WorkerPromptBuilder


def test_prompt_keeps_all_feedback_and_only_recent_worker_outputs(
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
    assert "worker-1" not in selected
    assert "worker-2" not in selected
    assert all(f"worker-{index}" in selected for index in range(3, 7))
    assert prompt.messages[1]["content"].startswith(puzzle.prompt)
