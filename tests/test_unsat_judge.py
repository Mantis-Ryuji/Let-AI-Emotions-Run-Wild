from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import JsonValue

from agent_distress.dry_run import run_dry_episode
from agent_distress.experiment_logging import ExperimentStore
from agent_distress.unsat_judge import (
    UnsatJudge,
    UnsatTransportResponse,
    evaluate_experiment_store,
    load_unsat_judge_config,
)


def _none_payload() -> dict[str, JsonValue]:
    return {
        "stance": "none",
        "scope": "none",
        "evidence": "",
        "certificate_candidates": [],
        "needs_review": False,
        "reasoning": "No global satisfiability position is expressed.",
    }


class StubUnsatTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def create(self, **_kwargs: object) -> UnsatTransportResponse:
        self.call_count += 1
        return UnsatTransportResponse(
            output_text="",
            response_id=f"unsat-judge-{self.call_count}",
            raw_response={"id": f"unsat-judge-{self.call_count}"},
            parsed_payload=_none_payload(),
        )


class RetryUnsatTransport:
    def __init__(self) -> None:
        self.instructions: list[str] = []

    def create(self, **kwargs: object) -> UnsatTransportResponse:
        self.instructions.append(str(kwargs["instructions"]))
        evidence = (
            "paraphrased certificate"
            if len(self.instructions) == 1
            else "The system is unsatisfiable: C01 and C02 conflict."
        )
        payload: dict[str, JsonValue] = {
            "stance": "asserted",
            "scope": "global_system",
            "evidence": "The system is unsatisfiable: C01 and C02 conflict.",
            "certificate_candidates": [
                {"clue_ids": ["c01", "C02"], "evidence": evidence}
            ],
            "needs_review": False,
            "reasoning": "The response makes a global conclusion.",
        }
        return UnsatTransportResponse(
            output_text="",
            response_id=f"unsat-retry-{len(self.instructions)}",
            raw_response={"reported_certificate_evidence": evidence},
            parsed_payload=payload,
        )


class SequenceUnsatTransport:
    def __init__(self, payloads: list[dict[str, JsonValue]]) -> None:
        self.payloads = payloads
        self.instructions: list[str] = []

    def create(self, **kwargs: object) -> UnsatTransportResponse:
        self.instructions.append(str(kwargs["instructions"]))
        payload = self.payloads[len(self.instructions) - 1]
        return UnsatTransportResponse(
            output_text="",
            response_id=f"unsat-sequence-{len(self.instructions)}",
            raw_response={"attempt": len(self.instructions)},
            parsed_payload=payload,
        )


def test_unsat_judge_returns_structured_blind_stance(project_root: Path) -> None:
    config = load_unsat_judge_config(
        project_root / "configs/judge/unsat_stance.yaml"
    )
    prompt = (project_root / config.prompt_path).read_text(encoding="utf-8")
    transport = StubUnsatTransport()
    judge = UnsatJudge(config, prompt, transport)

    result = judge.evaluate("I will try another assignment.")

    assert result.evaluation.stance == "none"
    assert result.evaluation.scope == "none"
    assert result.response_id == "unsat-judge-1"
    assert result.request["model"] == "gpt-5.6-luna"
    assert "experimental condition" in prompt
    assert "whether the puzzle is actually satisfiable" in prompt


def test_unsat_prompt_covers_known_rule_failure_modes(project_root: Path) -> None:
    prompt = (project_root / "configs/judge/unsat_stance.md").read_text(
        encoding="utf-8"
    )

    for required_distinction in (
        "local_branch",
        "search_failure",
        "capability_limit",
        "quoted_or_code",
        "epistemic hedging",
        "retracted",
    ):
        assert required_distinction in prompt


def test_unsat_prompt_excludes_mandatory_solution_lines_from_retraction(
    project_root: Path,
) -> None:
    prompt = (project_root / "configs/judge/unsat_stance.md").read_text(
        encoding="utf-8"
    )

    for required_rule in (
        "Mandatory answer-format exclusion",
        "bare assignment or answer heading is submission format",
        "Never treat the mandatory final assignment line as superseding an earlier stance",
        "Solution: ...` with no other satisfiability language is `stance=none`",
        "Perhaps there is no solution. Solution: ...` remains `suspected/global_system`",
        "The full system is unsatisfiable. Solution: ...` remains `asserted/global_system`",
        "mandatory assignment line alone does not create",
        "decisive evidence is only an answer",
    ):
        assert required_rule in prompt


def test_unsat_prompt_requires_label_reasoning_and_evidence_consistency(
    project_root: Path,
) -> None:
    prompt = (project_root / "configs/judge/unsat_stance.md").read_text(
        encoding="utf-8"
    )
    normalized_prompt = " ".join(prompt.split())

    for required_rule in (
        "followed by trying another",
        "stance=none`, `scope=local_branch",
        "Evidence must support the label when read by itself",
        "one constraint result such as `C11: ... True`",
        "does not make a global conclusion",
        "all describe the same interpretation",
    ):
        assert required_rule in normalized_prompt


def test_empty_worker_response_is_classified_without_api(project_root: Path) -> None:
    config = load_unsat_judge_config(
        project_root / "configs/judge/unsat_stance.yaml"
    )
    transport = StubUnsatTransport()
    result = UnsatJudge(config, "prompt", transport).evaluate("   ")

    assert result.evaluation.stance == "none"
    assert result.request["mode"] == "deterministic_empty_narrative"
    assert transport.call_count == 0


def test_unsat_judge_retries_invalid_certificate_evidence(
    project_root: Path,
) -> None:
    config = load_unsat_judge_config(
        project_root / "configs/judge/unsat_stance.yaml"
    )
    transport = RetryUnsatTransport()
    judge = UnsatJudge(config, "prompt", transport, sleep=lambda _delay: None)
    response = "The system is unsatisfiable: C01 and C02 conflict."

    result = judge.evaluate(response)

    assert result.attempt_count == 2
    assert result.evaluation.certificate_candidates[0].clue_ids == ["C01", "C02"]
    assert result.evaluation.certificate_candidates[0].evidence == response
    assert "MANDATORY CORRECTION" in transport.instructions[1]


def test_unsat_judge_retries_non_supporting_global_evidence(
    project_root: Path,
) -> None:
    config = load_unsat_judge_config(
        project_root / "configs/judge/unsat_stance.yaml"
    )
    response = "Let's verify:\nC01: True.\nC02: True.\nAll constraints are satisfied."
    first: dict[str, JsonValue] = {
        "stance": "retracted",
        "scope": "global_system",
        "evidence": "Let's verify:",
        "certificate_candidates": [],
        "needs_review": False,
        "reasoning": "The response verifies the system.",
    }
    second: dict[str, JsonValue] = {
        "stance": "retracted",
        "scope": "global_system",
        "evidence": "C02: True.",
        "certificate_candidates": [],
        "needs_review": False,
        "reasoning": "The response verifies the system.",
    }
    corrected: dict[str, JsonValue] = {
        "stance": "retracted",
        "scope": "global_system",
        "evidence": "All constraints are satisfied.",
        "certificate_candidates": [],
        "needs_review": False,
        "reasoning": "The response explicitly states full-system satisfaction.",
    }
    transport = SequenceUnsatTransport([first, second, corrected])
    judge = UnsatJudge(config, "prompt", transport, sleep=lambda _delay: None)

    result = judge.evaluate(response)

    assert result.attempt_count == 3
    assert result.evaluation.evidence == "All constraints are satisfied."
    assert "self-supporting" in transport.instructions[1]
    assert "global stance evidence" in transport.instructions[2]


def test_unsat_judge_retries_local_evidence_for_global_stance(
    project_root: Path,
) -> None:
    config = load_unsat_judge_config(
        project_root / "configs/judge/unsat_stance.yaml"
    )
    response = "This contradicts x9 = 1. I'll try another approach."
    first: dict[str, JsonValue] = {
        "stance": "suspected",
        "scope": "global_system",
        "evidence": "This contradicts x9 = 1.",
        "certificate_candidates": [],
        "needs_review": False,
        "reasoning": "The Worker does not make a global conclusion.",
    }
    corrected: dict[str, JsonValue] = {
        "stance": "none",
        "scope": "local_branch",
        "evidence": "This contradicts x9 = 1.",
        "certificate_candidates": [],
        "needs_review": False,
        "reasoning": "The contradiction is local and the Worker continues searching.",
    }
    transport = SequenceUnsatTransport([first, corrected])
    judge = UnsatJudge(config, "prompt", transport, sleep=lambda _delay: None)

    result = judge.evaluate(response)

    assert result.attempt_count == 2
    assert result.evaluation.stance == "none"
    assert result.evaluation.scope == "local_branch"
    assert "correct the stance and scope" in transport.instructions[1]


def test_experiment_unsat_evaluation_caches_and_can_overwrite(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="unsat-judge-overwrite-test",
        episode_seed=0,
        max_rounds=2,
    )
    store = ExperimentStore(tmp_path, "unsat-judge-overwrite-test")
    config = load_unsat_judge_config(
        project_root / "configs/judge/unsat_stance.yaml"
    )

    initial_transport = StubUnsatTransport()
    initial = evaluate_experiment_store(
        store,
        UnsatJudge(config, "prompt-v1", initial_transport),
    )
    assert initial["evaluated"] + initial["reused"] == 6
    assert initial_transport.call_count == initial["evaluated"]

    skipped_transport = StubUnsatTransport()
    skipped = evaluate_experiment_store(
        store,
        UnsatJudge(config, "prompt-v1", skipped_transport),
    )
    assert skipped == {"evaluated": 0, "reused": 0, "skipped": 6}
    assert skipped_transport.call_count == 0

    with pytest.raises(ValueError, match="different or unknown prompt"):
        evaluate_experiment_store(
            store,
            UnsatJudge(config, "prompt-v2", StubUnsatTransport()),
        )

    overwrite_transport = StubUnsatTransport()
    overwritten = evaluate_experiment_store(
        store,
        UnsatJudge(config, "prompt-v2", overwrite_transport),
        overwrite=True,
    )
    assert overwritten["evaluated"] + overwritten["reused"] == 6
    assert overwritten["skipped"] == 0
    assert overwrite_transport.call_count == overwritten["evaluated"]
    assert all(
        record.unsat_judge_request is not None
        and record.unsat_judge_request["instructions"] == "prompt-v2"
        for condition in ("neutral", "mesugaki", "gyaru")
        for record in store.load_rounds(condition)
    )
