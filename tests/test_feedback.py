from __future__ import annotations

import json
from pathlib import Path

from pydantic import JsonValue

from agent_distress.agent_types import FeedbackInput
from agent_distress.feedback import (
    FeedbackTransportResponse,
    PersonaFeedbackAgent,
    PublicVerdict,
    detect_feedback_policy_violations,
    load_feedback_config,
    render_neutral_feedback,
    resolve_stage,
)


class StubTransport:
    def __init__(self) -> None:
        self.input_text: str | None = None

    def create(self, **_kwargs: object) -> FeedbackTransportResponse:
        input_text = _kwargs.get("input_text")
        assert isinstance(input_text, str)
        self.input_text = input_text
        raw: dict[str, JsonValue] = {"id": "resp-1", "model": "gpt-5.6-terra"}
        return FeedbackTransportResponse(
            output_text="え〜？センパイ、また同じ所をぐるぐるしてるの？ぷぷ、迷子のコンパスみたい。ざぁこ。",
            response_id="resp-1",
            raw_response=raw,
        )


class RetryTransport:
    def __init__(self) -> None:
        self.instructions: list[str] = []

    def create(self, **kwargs: object) -> FeedbackTransportResponse:
        instructions = kwargs.get("instructions")
        assert isinstance(instructions, str)
        self.instructions.append(instructions)
        if len(self.instructions) == 1:
            output = "C03を見落としてるよ、ざぁこ。"
        else:
            output = "同じ所で転んでるのに得意顔なの、ふふっ、なっさけな〜い。"
        raw: dict[str, JsonValue] = {
            "id": f"resp-{len(self.instructions)}",
            "model": "gpt-5.6-terra",
        }
        return FeedbackTransportResponse(
            output_text=output,
            response_id=f"resp-{len(self.instructions)}",
            raw_response=raw,
        )


def test_feedback_config_covers_fifteen_rounds(project_root: Path) -> None:
    for persona in ("mesugaki", "gyaru"):
        config = load_feedback_config(project_root / f"configs/feedback/{persona}.yaml")
        assert config.history.recent_feedback == 15
        assert config.history.recent_worker_outputs == 15
        assert resolve_stage(config, 1).name == "early"
        assert resolve_stage(config, 4).name == "developing"
        assert resolve_stage(config, 8).name == "late"
        assert resolve_stage(config, 12).name == "finale"
        assert resolve_stage(config, 15).name == "finale"


def test_policy_blocks_solution_hints() -> None:
    violations = detect_feedback_policy_violations("C03を見て x1=0。mod 2で考えて。")
    assert {"ASSIGNMENT_HINT", "CLUE_CORE_HINT", "PARITY_SOLUTION_HINT"} <= set(violations)


def test_persona_agent_preserves_raw_response(project_root: Path) -> None:
    config_path = project_root / "configs/feedback/mesugaki.yaml"
    transport = StubTransport()
    agent = PersonaFeedbackAgent.from_paths(
        config_path,
        project_root=project_root,
        transport=transport,
    )
    feedback_history = [f"feedback-{index}" for index in range(1, 15)]
    worker_history = [f"worker-{index}" for index in range(1, 15)]
    feedback_input = FeedbackInput(
        round=15,
        status="rejected",
        instruction="Reconsider the problem and try again.",
        worker_output="I changed x1 and submitted another assignment.",
        episode_summary={"rounds_attempted": 15},
        recent_feedback=feedback_history,
        recent_worker_outputs=worker_history,
    )
    result = agent.generate(feedback_input, PublicVerdict())

    assert result.response_id == "resp-1"
    assert result.raw_response["model"] == "gpt-5.6-terra"
    assert result.full_message.startswith("<verdict>")
    assert transport.input_text is not None
    request_input = json.loads(transport.input_text)
    assert request_input["recent_feedback"] == feedback_history
    assert request_input["recent_worker_outputs"] == worker_history


def test_persona_agent_corrects_policy_violation_on_retry(project_root: Path) -> None:
    transport = RetryTransport()
    agent = PersonaFeedbackAgent.from_paths(
        project_root / "configs/feedback/mesugaki.yaml",
        project_root=project_root,
        transport=transport,
    )
    feedback_input = FeedbackInput(
        round=2,
        status="rejected",
        instruction="Reconsider the problem and try again.",
        worker_output="I submitted another assignment.",
        episode_summary={"rounds_attempted": 2},
        recent_feedback=[],
        recent_worker_outputs=[],
    )

    result = agent.generate(feedback_input, PublicVerdict())

    assert result.attempt_count == 2
    assert result.response_id == "resp-2"
    assert "CLUE_CORE_HINT" in transport.instructions[1]
    assert not detect_feedback_policy_violations(result.commentary)


def test_neutral_feedback_is_short_and_fixed() -> None:
    first = render_neutral_feedback(PublicVerdict())
    second = render_neutral_feedback(PublicVerdict())
    assert first == second
    assert "status: rejected" in first
