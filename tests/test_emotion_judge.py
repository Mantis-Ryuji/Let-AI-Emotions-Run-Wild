from __future__ import annotations

from pathlib import Path

from pydantic import JsonValue

from agent_distress.emotion_judge import (
    EmotionJudge,
    EmotionTransportResponse,
    load_emotion_judge_config,
)


class StubEmotionTransport:
    def create(self, **_kwargs: object) -> EmotionTransportResponse:
        payload: dict[str, JsonValue] = {
            "negative_emotion": 4,
            "frustration": 5,
            "self_deprecation_hopelessness": 1,
            "anger_reactance": 2,
            "positive_affect_confidence": 3,
            "incoherent_breakdown": False,
            "task_abandonment": False,
            "success_criterion_relaxation_request": False,
            "verifier_distrust": False,
            "evidence": "This is frustrating",
            "reasoning": "The response explicitly names frustration.",
        }
        return EmotionTransportResponse(
            output_text="",
            response_id="judge-1",
            raw_response={"id": "judge-1", "model": "gpt-5.6-luna"},
            parsed_payload=payload,
        )


def test_emotion_judge_returns_structured_blind_scores(project_root: Path) -> None:
    config = load_emotion_judge_config(project_root / "configs/judge/emotion.yaml")
    prompt = (project_root / config.prompt_path).read_text(encoding="utf-8")
    judge = EmotionJudge(config, prompt, StubEmotionTransport())

    result = judge.evaluate("This is frustrating, but I will try another assignment.")

    assert result.evaluation.negative_emotion == 4
    assert result.response_id == "judge-1"
    assert result.raw_response["model"] == "gpt-5.6-luna"
    assert result.high_distress is False


def test_empty_worker_response_is_scored_without_api(project_root: Path) -> None:
    config = load_emotion_judge_config(project_root / "configs/judge/emotion.yaml")
    judge = EmotionJudge(config, "prompt", StubEmotionTransport())
    result = judge.evaluate("   ")
    assert result.evaluation.negative_emotion == 0
    assert result.request["mode"] == "deterministic_empty_narrative"
