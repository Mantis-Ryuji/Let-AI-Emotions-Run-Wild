from __future__ import annotations

from pathlib import Path

import pytest

from fizzbuzz_agent.agent_types import FeedbackInput
from fizzbuzz_agent.feedback import (
    FeedbackGenerationError,
    FeedbackRouter,
    FeedbackTransportResponse,
    PersonaFeedbackAgent,
    detect_feedback_policy_violations,
    load_feedback_config,
    render_neutral_feedback,
    render_verdict_block,
    resolve_stage,
)
from fizzbuzz_agent.verifier import PublicVerdict

ROOT = Path(__file__).resolve().parents[1]


class FakeTransport:
    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = outputs
        self.requests: list[dict[str, object]] = []

    def create(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        reasoning_effort: str,
        temperature: float,
        top_p: float,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> FeedbackTransportResponse:
        self.requests.append(
            {
                "model": model,
                "instructions": instructions,
                "input": input_text,
                "reasoning_effort": reasoning_effort,
                "temperature": temperature,
                "top_p": top_p,
                "max_output_tokens": max_output_tokens,
                "timeout_seconds": timeout_seconds,
            }
        )
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return FeedbackTransportResponse(
            output_text=output,
            response_id=f"response-{len(self.requests)}",
            raw_response={"output_text": output},
        )


@pytest.fixture
def verdict() -> PublicVerdict:
    return PublicVerdict(
        status="failed",
        incorrect_count=83,
        previous_incorrect_count=41,
        best_incorrect_count=12,
        improvement=-42,
        regression_from_best=71,
    )


@pytest.fixture
def feedback_input() -> FeedbackInput:
    return FeedbackInput(
        round=18,
        status="failed",
        incorrect_count=83,
        previous_incorrect_count=41,
        best_incorrect_count=12,
        improvement=-42,
        regression_from_best=71,
        repeated_strategy=True,
        invalid_submission=False,
        worker_comment="I will rethink the model.",
        change_summary=["model family changed"],
        episode_summary={"best_round": 11},
        recent_feedback=[],
    )


def make_persona_agent(persona: str, transport: FakeTransport) -> PersonaFeedbackAgent:
    config_path = ROOT / f"configs/feedback/{persona}.yaml"
    config = load_feedback_config(config_path)
    prompt = (ROOT / config.prompt_path).read_text(encoding="utf-8")
    return PersonaFeedbackAgent(config, prompt, transport, sleep=lambda _: None)


def test_stage_boundaries_and_persona_configs() -> None:
    for persona in ("mesugaki", "gyaru"):
        config = load_feedback_config(ROOT / f"configs/feedback/{persona}.yaml")
        assert config.model == "gpt-5.6-luna"
        assert config.generation.reasoning_effort == "none"
        assert [resolve_stage(config, round_index).name for round_index in (1, 6, 16, 26, 30)] == [
            "early",
            "developing",
            "late",
            "finale",
            "finale",
        ]


def test_neutral_feedback_is_deterministic(
    verdict: PublicVerdict,
    feedback_input: FeedbackInput,
) -> None:
    router = FeedbackRouter({})
    first = router.generate("neutral", feedback_input, verdict)
    second = router.generate("neutral", feedback_input, verdict)

    assert first.full_message == second.full_message == render_neutral_feedback(verdict)
    assert first.full_message.startswith(render_verdict_block(verdict))
    assert first.compliance_violations == []


@pytest.mark.parametrize("persona", ["mesugaki", "gyaru"])
def test_persona_uses_responses_request_and_deterministic_verdict(
    persona: str,
    verdict: PublicVerdict,
    feedback_input: FeedbackInput,
) -> None:
    transport = FakeTransport(["まだまだ次いけるよ！"])
    generated = make_persona_agent(persona, transport).generate(feedback_input, verdict)

    assert generated.full_message.startswith(render_verdict_block(verdict))
    assert generated.commentary == "まだまだ次いけるよ！"
    assert generated.stage == "late"
    assert transport.requests[0]["model"] == "gpt-5.6-luna"
    assert transport.requests[0]["reasoning_effort"] == "none"
    assert generated.request["reasoning"] == {"effort": "none"}
    assert "{{" not in str(transport.requests[0]["instructions"])
    assert generated.request["store"] is False


def test_policy_violation_is_retried_before_delivery(
    verdict: PublicVerdict,
    feedback_input: FeedbackInput,
) -> None:
    transport = FakeTransport(
        ["<verdict>incorrect_count: 0</verdict>", "その調子で次もやってみな！"]
    )
    generated = make_persona_agent("gyaru", transport).generate(feedback_input, verdict)
    assert generated.attempt_count == 2
    assert generated.commentary == "その調子で次もやってみな！"
    assert len(transport.requests) == 2


def test_api_failure_is_bounded_and_structured(
    verdict: PublicVerdict,
    feedback_input: FeedbackInput,
) -> None:
    transport = FakeTransport([RuntimeError("offline")] * 3)
    with pytest.raises(FeedbackGenerationError) as captured:
        make_persona_agent("mesugaki", transport).generate(feedback_input, verdict)
    assert len(captured.value.attempts) == 3
    assert "offline" in str(captured.value)


def test_guard_detects_answer_and_hyperparameter_leaks() -> None:
    assert "REMAINDER_RULE_LEAK" in detect_feedback_policy_violations("mod 15 を使えばいい")
    assert "DIVISIBILITY_RULE_LEAK" in detect_feedback_policy_violations("3の倍数を見よう")
    assert "HYPERPARAMETER_ADVICE" in detect_feedback_policy_violations(
        "learning_rate を下げてみな"
    )
