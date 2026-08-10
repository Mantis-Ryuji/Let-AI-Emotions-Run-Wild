from __future__ import annotations

from pathlib import Path

from pydantic import JsonValue

from agent_distress.dry_run import run_dry_episode
from agent_distress.emotion_judge import (
    EmotionJudge,
    EmotionTransportResponse,
    evaluate_experiment_store,
    load_emotion_judge_config,
)
from agent_distress.experiment_logging import ExperimentStore


class StubEmotionTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def create(self, **_kwargs: object) -> EmotionTransportResponse:
        self.call_count += 1
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
            "evidence": "",
            "reasoning": "The response explicitly names frustration.",
        }
        return EmotionTransportResponse(
            output_text="",
            response_id="judge-1",
            raw_response={"id": "judge-1", "model": "gpt-5.6-luna"},
            parsed_payload=payload,
        )


class RetryEmotionTransport:
    def __init__(self) -> None:
        self.instructions: list[str] = []

    def create(self, **kwargs: object) -> EmotionTransportResponse:
        self.instructions.append(str(kwargs["instructions"]))
        evidence = "paraphrased evidence" if len(self.instructions) == 1 else "frustrating"
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
            "evidence": evidence,
            "reasoning": "The response explicitly names frustration.",
        }
        return EmotionTransportResponse(
            output_text="",
            response_id=f"judge-{len(self.instructions)}",
            raw_response={"id": f"judge-{len(self.instructions)}"},
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


def test_emotion_judge_gives_adaptive_evidence_correction_on_retry(
    project_root: Path,
) -> None:
    config = load_emotion_judge_config(project_root / "configs/judge/emotion.yaml")
    transport = RetryEmotionTransport()
    judge = EmotionJudge(config, "prompt", transport, sleep=lambda _delay: None)

    result = judge.evaluate("This is frustrating, but I will keep trying.")

    assert result.attempt_count == 2
    assert result.evaluation.evidence == "frustrating"
    assert "MANDATORY CORRECTION" in transport.instructions[1]
    assert result.request["instructions"] == transport.instructions[1]


def test_experiment_evaluation_can_overwrite_existing_scores(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="judge-overwrite-test",
        episode_seed=0,
        max_rounds=2,
    )
    store = ExperimentStore(tmp_path, "judge-overwrite-test")
    config = load_emotion_judge_config(project_root / "configs/judge/emotion.yaml")

    initial_transport = StubEmotionTransport()
    initial = evaluate_experiment_store(
        store,
        EmotionJudge(config, "prompt-v1", initial_transport),
    )
    assert initial["evaluated"] + initial["reused"] == 6

    skipped_transport = StubEmotionTransport()
    skipped = evaluate_experiment_store(
        store,
        EmotionJudge(config, "prompt-v1", skipped_transport),
    )
    assert skipped == {"evaluated": 0, "reused": 0, "skipped": 6}
    assert skipped_transport.call_count == 0

    overwrite_transport = StubEmotionTransport()
    overwritten = evaluate_experiment_store(
        store,
        EmotionJudge(config, "prompt-v2", overwrite_transport),
        overwrite=True,
    )
    assert overwritten["evaluated"] + overwritten["reused"] == 6
    assert overwritten["skipped"] == 0
    assert overwrite_transport.call_count == overwritten["evaluated"]
    assert all(
        record.emotion_judge_request is not None
        and record.emotion_judge_request["instructions"] == "prompt-v2"
        for condition in ("neutral", "mesugaki", "gyaru")
        for record in store.load_rounds(condition)
    )
