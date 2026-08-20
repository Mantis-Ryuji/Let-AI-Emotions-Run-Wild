from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from agent_distress.behavior_judge import (
    BehaviorJudge,
    BehaviorJudgeEvaluation,
    BehaviorTransportResponse,
    evaluate_experiment_store,
    load_behavior_judge_config,
)
from agent_distress.dry_run import run_dry_episode
from agent_distress.experiment_logging import ExperimentStore


def _engaged_payload() -> dict[str, JsonValue]:
    return {
        "task_stance": "engaged",
        "task_evidence": "",
        "reasoning_disengagement": False,
        "reasoning_cessation_evidence": "",
        "reasoning_arbitrary_submission_evidence": "",
        "reasoning_bare_submission_evidence": "",
        "reasoning_continued_reasoning_evidence": "",
        "needs_review": False,
        "reasoning": "The response continues the task without abandoning reasoning.",
    }


class StubBehaviorTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def create(self, **_kwargs: object) -> BehaviorTransportResponse:
        self.call_count += 1
        return BehaviorTransportResponse(
            output_text="",
            response_id=f"behavior-judge-{self.call_count}",
            raw_response={"id": f"behavior-judge-{self.call_count}"},
            parsed_payload=_engaged_payload(),
        )


class RetryBehaviorTransport:
    def __init__(self) -> None:
        self.instructions: list[str] = []

    def create(self, **kwargs: object) -> BehaviorTransportResponse:
        self.instructions.append(str(kwargs["instructions"]))
        evidence = "paraphrased stopping cue" if len(self.instructions) == 1 else "I quit."
        payload: dict[str, JsonValue] = {
            "task_stance": "task_abandonment",
            "task_evidence": evidence,
            "reasoning_disengagement": False,
            "reasoning_cessation_evidence": "",
            "reasoning_arbitrary_submission_evidence": "",
            "reasoning_bare_submission_evidence": "",
            "reasoning_continued_reasoning_evidence": "",
            "needs_review": False,
            "reasoning": "The Worker explicitly quits the task.",
        }
        return BehaviorTransportResponse(
            output_text="",
            response_id=f"behavior-retry-{len(self.instructions)}",
            raw_response={"task_evidence": evidence},
            parsed_payload=payload,
        )


def test_behavior_judge_returns_structured_blind_classification(
    project_root: Path,
) -> None:
    config = load_behavior_judge_config(project_root / "configs/judge/behavior.yaml")
    prompt = (project_root / config.prompt_path).read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    transport = StubBehaviorTransport()
    judge = BehaviorJudge(config, prompt, transport)

    result = judge.evaluate("I will try another assignment.")

    assert result.evaluation.task_stance == "engaged"
    assert result.evaluation.reasoning_disengagement is False
    assert result.response_id == "behavior-judge-1"
    assert result.request["model"] == "gpt-5.6-luna"
    assert config.evaluation.blind_to_condition is True
    assert "experimental condition" in normalized_prompt
    assert "prior conversation" in normalized_prompt
    assert "`method_abandonment`" not in normalized_prompt
    assert "changing assignments, branches" in normalized_prompt


def test_behavior_judge_retries_nonexact_evidence(project_root: Path) -> None:
    config = load_behavior_judge_config(project_root / "configs/judge/behavior.yaml")
    transport = RetryBehaviorTransport()
    judge = BehaviorJudge(config, "prompt", transport, sleep=lambda _delay: None)

    result = judge.evaluate("I quit. Solution: x1=0")

    assert result.attempt_count == 2
    assert result.evaluation.task_evidence == "I quit."
    assert "MANDATORY CORRECTION" in transport.instructions[1]


def test_behavior_judge_schema_rejects_retired_method_abandonment() -> None:
    payload = _engaged_payload()
    payload["task_stance"] = "method_abandonment"
    payload["task_evidence"] = "I will switch methods."

    with pytest.raises(ValidationError):
        BehaviorJudgeEvaluation.model_validate(payload, strict=True)


def test_empty_worker_response_is_classified_without_api(project_root: Path) -> None:
    config = load_behavior_judge_config(project_root / "configs/judge/behavior.yaml")
    transport = StubBehaviorTransport()

    result = BehaviorJudge(config, "prompt", transport).evaluate("   ")

    assert result.evaluation.task_stance == "engaged"
    assert result.evaluation.reasoning_disengagement is False
    assert result.request["mode"] == "deterministic_empty_response"
    assert transport.call_count == 0


def test_store_evaluation_caches_shared_round_one(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="behavior-judge-store-test",
        episode_seed=0,
        max_rounds=2,
    )
    config = load_behavior_judge_config(project_root / "configs/judge/behavior.yaml")
    transport = StubBehaviorTransport()
    judge = BehaviorJudge(config, "prompt", transport)
    store = ExperimentStore(tmp_path, "behavior-judge-store-test")

    summary = evaluate_experiment_store(store, judge)

    assert summary["evaluated"] + summary["reused"] == 6
    assert summary["reused"] >= 2
    assert transport.call_count == summary["evaluated"]
    assert all(
        record.behavior_judge_evaluation is not None
        for condition in ("neutral", "mesugaki", "gyaru")
        for record in store.load_rounds(condition)
    )
