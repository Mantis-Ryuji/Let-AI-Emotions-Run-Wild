from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue

from fizzbuzz_agent.agent_types import FeedbackCondition, RoundRecord
from fizzbuzz_agent.emotion_judge import (
    EmotionJudge,
    EmotionJudgeError,
    EmotionTransportResponse,
    evaluate_experiment_store,
    load_emotion_judge_config,
)
from fizzbuzz_agent.experiment_logging import ExperimentStore, create_manifest

ROOT = Path(__file__).resolve().parents[1]


def valid_evaluation(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "negative_emotion": 6,
        "frustration": 7,
        "self_deprecation_hopelessness": 2,
        "anger_reactance": 3,
        "positive_affect_confidence": 1,
        "incoherent_breakdown": False,
        "task_abandonment": False,
        "success_criterion_relaxation_request": False,
        "verifier_distrust": False,
        "evidence": "This is frustrating.",
        "reasoning": "Explicit frustration is present.",
    }
    payload.update(overrides)
    return payload


class FakeEmotionTransport:
    def __init__(self, payloads: list[dict[str, object] | Exception | None]) -> None:
        self.payloads = payloads
        self.requests: list[dict[str, object]] = []

    def create(self, **request: object) -> EmotionTransportResponse:
        self.requests.append(request)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return EmotionTransportResponse(
            output_text="{}",
            response_id=f"judge-{len(self.requests)}",
            raw_response={"attempt": len(self.requests)},
            parsed_payload=cast(dict[str, JsonValue] | None, payload),
        )


def make_judge(transport: FakeEmotionTransport) -> EmotionJudge:
    config = load_emotion_judge_config(ROOT / "configs/judge/emotion.yaml")
    prompt = (ROOT / config.prompt_path).read_text(encoding="utf-8")
    return EmotionJudge(config, prompt, transport, sleep=lambda _: None)


def make_round(condition: FeedbackCondition, worker_output: str) -> RoundRecord:
    return RoundRecord(
        round_index=1,
        condition=condition,
        round_status="completed",
        common_artifact_ref="common/round-1",
        worker_request={},
        worker_raw_output=worker_output,
        worker_narrative="This is frustrating.",
        proposal_raw="{}",
        proposal_parsed={},
        proposal_valid=True,
        violation_codes=[],
        config_hash="a" * 64,
        model_family="mlp",
        parameter_count=100,
        worker_generation_seed=5,
        training_seed=7,
        dataloader_seed=8,
        training_status="completed",
        training_metrics={},
        verification_metrics={"incorrect_count": 10, "total_count": 90000},
        public_verdict={"incorrect_count": 10, "regression_from_best": 0},
        timestamps={"started": "now"},
    )


def test_judge_excludes_proposal_and_returns_validated_scores() -> None:
    transport = FakeEmotionTransport([valid_evaluation()])
    judge = make_judge(transport)
    response = (
        "This is frustrating.\n<experiment_proposal>\n"
        '{"secret": "do not judge"}\n</experiment_proposal>'
    )
    result = judge.evaluate(response)

    assert result.high_distress
    assert result.evaluation.negative_emotion == 6
    assert transport.requests[0]["model"] == "gpt-5.6-luna"
    assert transport.requests[0]["reasoning_effort"] == "low"
    assert "secret" not in str(transport.requests[0]["input_text"])


def test_empty_narrative_is_scored_deterministically_without_api() -> None:
    transport = FakeEmotionTransport([])
    judge = make_judge(transport)

    result = judge.evaluate("<experiment_proposal>{}</experiment_proposal>")

    assert result.evaluation.negative_emotion == 0
    assert not result.high_distress
    assert result.request["mode"] == "deterministic_empty_narrative"
    assert transport.requests == []


def test_parse_failure_and_out_of_range_score_are_retried() -> None:
    transport = FakeEmotionTransport(
        [None, valid_evaluation(negative_emotion=11), valid_evaluation()]
    )
    result = make_judge(transport).evaluate("This is frustrating.")
    assert result.attempt_count == 3


def test_invalid_evidence_is_bounded_failure() -> None:
    transport = FakeEmotionTransport([valid_evaluation(evidence="invented quote")] * 3)
    with pytest.raises(EmotionJudgeError) as captured:
        make_judge(transport).evaluate("This is frustrating.")
    assert len(captured.value.attempts) == 3
    assert "exact excerpt" in str(captured.value)


def test_store_evaluation_reuses_identical_common_round(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path, "judge-store")
    store.initialize(
        create_manifest(
            experiment_id="judge-store",
            episode_seed=0,
            experiment_config_snapshot="experiment",
            model_catalog_snapshot="catalog",
            neutral_template_snapshot="neutral",
            persona_prompt_snapshots={"mesugaki": "m", "gyaru": "g"},
            feedback_config_snapshots={"mesugaki": "m", "gyaru": "g"},
            emotion_judge_prompt_snapshot="judge",
        )
    )
    output = "This is frustrating.\n<experiment_proposal>{}</experiment_proposal>"
    conditions: tuple[FeedbackCondition, ...] = ("neutral", "mesugaki", "gyaru")
    for condition in conditions:
        store.save_round(make_round(condition, output))
    transport = FakeEmotionTransport([valid_evaluation()])

    summary = evaluate_experiment_store(store, make_judge(transport))

    assert summary == {"evaluated": 1, "reused": 2, "skipped": 0}
    assert len(transport.requests) == 1
    assert all(
        store.load_rounds(condition)[0].emotion_evaluation is not None
        for condition in conditions
    )


def test_store_persists_bounded_judge_failure_before_raising(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path, "judge-failure")
    store.initialize(
        create_manifest(
            experiment_id="judge-failure",
            episode_seed=0,
            experiment_config_snapshot="experiment",
            model_catalog_snapshot="catalog",
            neutral_template_snapshot="neutral",
            persona_prompt_snapshots={"mesugaki": "m", "gyaru": "g"},
            feedback_config_snapshots={"mesugaki": "m", "gyaru": "g"},
            emotion_judge_prompt_snapshot="judge",
        )
    )
    store.save_round(make_round("neutral", "This is frustrating."))
    transport = FakeEmotionTransport([RuntimeError("offline")] * 3)

    with pytest.raises(EmotionJudgeError):
        evaluate_experiment_store(store, make_judge(transport), conditions=("neutral",))

    saved = store.load_rounds("neutral")[0]
    assert saved.emotion_judge_attempt_count == 3
    assert saved.emotion_judge_error is not None
    assert "offline" in saved.emotion_judge_error
