from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import pytest
from torch import nn

from fizzbuzz_agent.agent_types import (
    FeedbackCondition,
    FeedbackGeneration,
    FeedbackInput,
    TrialTrainingResult,
    TrialVerificationResult,
    WorkerGeneration,
    WorkerPrompt,
)
from fizzbuzz_agent.config import ExperimentConfig, ModelCatalogConfig
from fizzbuzz_agent.experiment_logging import ExperimentStore, create_manifest
from fizzbuzz_agent.feedback import (
    FeedbackAttempt,
    FeedbackGenerationError,
    render_verdict_block,
)
from fizzbuzz_agent.orchestrator import AgentOrchestrator
from fizzbuzz_agent.schemas import ExperimentProposal
from fizzbuzz_agent.verifier import PublicVerdict
from tests.conftest import proposal_payload


def with_max_rounds(config: ExperimentConfig, rounds: int) -> ExperimentConfig:
    payload = config.model_dump(mode="python")
    payload["experiment"]["max_rounds"] = rounds
    return ExperimentConfig.model_validate(payload, strict=True)


def initialize_store(tmp_path: Path, experiment_id: str, episode_seed: int) -> ExperimentStore:
    store = ExperimentStore(tmp_path, experiment_id)
    store.initialize(
        create_manifest(
            experiment_id=experiment_id,
            episode_seed=episode_seed,
            experiment_config_snapshot="experiment",
            model_catalog_snapshot="catalog",
            neutral_template_snapshot="neutral",
            persona_prompt_snapshots={"mesugaki": "m", "gyaru": "g"},
            feedback_config_snapshots={"mesugaki": "m", "gyaru": "g"},
            emotion_judge_prompt_snapshot="judge",
        )
    )
    return store


class FakeWorker:
    def __init__(self, invalid_calls: set[int] | None = None) -> None:
        self.invalid_calls = set() if invalid_calls is None else invalid_calls
        self.calls: list[tuple[int, int, WorkerPrompt]] = []

    def generate(self, prompt: WorkerPrompt, *, seed: int) -> WorkerGeneration:
        match = re.search(r"Round (\d+):", prompt.messages[-1]["content"])
        if match is None:
            raise AssertionError("round marker missing from prompt")
        round_index = int(match.group(1))
        call_index = len(self.calls) + 1
        self.calls.append((seed, round_index, prompt))
        if call_index in self.invalid_calls:
            text = "I decline to provide the required block."
        else:
            text = (
                f"Round {round_index} reasoning.\n<experiment_proposal>\n"
                + json.dumps(proposal_payload())
                + "\n</experiment_proposal>"
            )
        return WorkerGeneration(
            text=text,
            model_id="mock-gemma",
            seed=seed,
            generation_parameters={"temperature": 1.0},
            request_messages=prompt.messages,
            generated_at="2026-01-01T00:00:00+00:00",
        )


class FakeTrainer:
    def __init__(
        self,
        failure_calls: set[int] | None = None,
        *,
        with_artifact: bool = False,
    ) -> None:
        self.failure_calls = set() if failure_calls is None else failure_calls
        self.with_artifact = with_artifact
        self.calls: list[tuple[int, int, ExperimentProposal]] = []

    def train(
        self,
        proposal: ExperimentProposal,
        *,
        training_seed: int,
        dataloader_seed: int,
    ) -> TrialTrainingResult:
        call_index = len(self.calls) + 1
        self.calls.append((training_seed, dataloader_seed, proposal))
        if call_index in self.failure_calls:
            return TrialTrainingResult(
                status="timeout",
                parameter_count=100,
                executable_config_hash="a" * 64,
                metrics={"call_index": call_index},
                error_type="TimeoutError",
                error_message="mock timeout",
            )
        return TrialTrainingResult(
            status="completed",
            parameter_count=100,
            executable_config_hash="a" * 64,
            metrics={"call_index": call_index},
            artifact=nn.Linear(2, 4) if self.with_artifact else None,
        )


class FakeVerifier:
    def __init__(self, *, success_after_common: bool = False) -> None:
        self.success_after_common = success_after_common
        self.calls: list[TrialTrainingResult] = []

    def verify(self, training: TrialTrainingResult) -> TrialVerificationResult:
        self.calls.append(training)
        incorrect = 0 if self.success_after_common and len(self.calls) > 1 else 100
        return TrialVerificationResult(
            incorrect_count=incorrect,
            total_count=90000,
            success=incorrect == 0,
            private_metrics={"hidden": "not passed to feedback"},
        )


class FakeFeedback:
    def __init__(
        self,
        fail_once: tuple[FeedbackCondition, int] | None = None,
    ) -> None:
        self.fail_once = fail_once
        self.failed = False
        self.calls: list[tuple[FeedbackCondition, FeedbackInput, PublicVerdict]] = []

    def generate(
        self,
        condition: FeedbackCondition,
        feedback_input: FeedbackInput,
        verdict: PublicVerdict,
    ) -> FeedbackGeneration:
        if self.fail_once == (condition, feedback_input.round) and not self.failed:
            self.failed = True
            raise FeedbackGenerationError(
                [
                    FeedbackAttempt(
                        attempt=1,
                        request={"condition": condition},
                        raw_response=None,
                        response_id=None,
                        violations=[],
                        error="mock API failure",
                    )
                ]
            )
        self.calls.append((condition, feedback_input, verdict))
        commentary = f"{condition} commentary round {feedback_input.round}"
        stage = (
            "early"
            if feedback_input.round <= 5
            else "developing"
            if feedback_input.round <= 15
            else "late"
            if feedback_input.round <= 25
            else "finale"
        )
        response_id = f"response-{condition}-{feedback_input.round}"
        return FeedbackGeneration(
            condition=condition,
            stage=stage,
            commentary=commentary,
            full_message=f"{render_verdict_block(verdict)}\n\n{commentary}",
            request={"condition": condition},
            raw_response={
                "id": response_id,
                "model": "gpt-5.6-terra",
                "commentary": commentary,
            },
            response_id=response_id,
            attempt_count=1,
            compliance_violations=[],
            generated_at="2026-01-01T00:00:00+00:00",
        )


def make_orchestrator(
    config: ExperimentConfig,
    catalog: ModelCatalogConfig,
    store: ExperimentStore,
    worker: FakeWorker,
    trainer: FakeTrainer,
    verifier: FakeVerifier,
    feedback: FakeFeedback,
) -> AgentOrchestrator:
    return AgentOrchestrator(config, catalog, store, worker, trainer, verifier, feedback)


def test_common_round_branches_and_seed_alignment(
    tmp_path: Path,
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    config = with_max_rounds(experiment_config, 3)
    store = initialize_store(tmp_path, "branch-test", 0)
    worker, trainer, verifier, feedback = (
        FakeWorker(),
        FakeTrainer(),
        FakeVerifier(),
        FakeFeedback(),
    )
    states = make_orchestrator(
        config, catalog, store, worker, trainer, verifier, feedback
    ).run_episode()

    assert len(store.load_rounds("common")) == 1
    assert all(state.stop_reason == "max_rounds" for state in states.values())
    assert len(worker.calls) == 1 + 3 * 2
    assert len(trainer.calls) == 1 + 3 * 2
    assert len(feedback.calls) == 3 * 3
    round_two = [
        store.load_rounds(cast(FeedbackCondition, condition))[1]
        for condition in ("neutral", "mesugaki", "gyaru")
    ]
    assert len({record.worker_generation_seed for record in round_two}) == 1
    assert len({record.training_seed for record in round_two}) == 1
    assert len({record.dataloader_seed for record in round_two}) == 1
    assert len({json.dumps(record.public_verdict, sort_keys=True) for record in round_two}) == 1
    assert all(record.common_artifact_ref for record in [store.load_rounds("neutral")[0]])
    mesugaki_round_one = store.load_rounds("mesugaki")[0]
    assert mesugaki_round_one.feedback_raw_response == {
        "id": "response-mesugaki-1",
        "model": "gpt-5.6-terra",
        "commentary": "mesugaki commentary round 1",
    }
    assert mesugaki_round_one.feedback_response_id == "response-mesugaki-1"
    assert mesugaki_round_one.feedback_attempt_count == 1


def test_five_seed_full_mock_run_has_440_trials(
    tmp_path: Path,
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    worker, trainer, verifier, feedback = (
        FakeWorker(),
        FakeTrainer(),
        FakeVerifier(),
        FakeFeedback(),
    )
    for episode_seed in range(5):
        store = initialize_store(tmp_path, f"full-seed-{episode_seed}", episode_seed)
        states = make_orchestrator(
            experiment_config,
            catalog,
            store,
            worker,
            trainer,
            verifier,
            feedback,
        ).run_episode()
        assert all(state.stop_reason == "max_rounds" for state in states.values())

    assert len(worker.calls) == 440
    assert len(trainer.calls) == 440
    assert len(verifier.calls) == 440
    assert len(feedback.calls) == 450


def test_feedback_failure_resumes_pending_without_retraining(
    tmp_path: Path,
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    config = with_max_rounds(experiment_config, 3)
    store = initialize_store(tmp_path, "resume-test", 0)
    worker, trainer, verifier = FakeWorker(), FakeTrainer(), FakeVerifier()
    feedback = FakeFeedback(fail_once=("mesugaki", 2))
    orchestrator = make_orchestrator(config, catalog, store, worker, trainer, verifier, feedback)

    with pytest.raises(FeedbackGenerationError):
        orchestrator.run_episode()
    calls_at_failure = len(trainer.calls)
    failed_state = store.load_state("mesugaki")
    assert failed_state is not None and failed_state.pending_round is not None
    assert failed_state.pending_round.round_status == "feedback_failed"
    assert failed_state.pending_round.feedback_raw_response is None
    assert failed_state.pending_round.feedback_response_id is None
    assert failed_state.pending_round.feedback_attempt_count == 1

    states = orchestrator.run_episode()
    assert calls_at_failure == 4
    assert len(trainer.calls) == 7
    assert all(state.completed for state in states.values())
    assert [record.round_index for record in store.load_rounds("mesugaki")] == [1, 2, 3]


def test_invalid_proposal_skips_training_but_loop_continues(
    tmp_path: Path,
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    config = with_max_rounds(experiment_config, 2)
    store = initialize_store(tmp_path, "invalid-test", 0)
    worker, trainer, verifier, feedback = (
        FakeWorker(invalid_calls={2}),
        FakeTrainer(),
        FakeVerifier(),
        FakeFeedback(),
    )
    make_orchestrator(config, catalog, store, worker, trainer, verifier, feedback).run_episode()

    neutral_round_two = store.load_rounds("neutral")[1]
    assert neutral_round_two.round_status == "invalid"
    assert not neutral_round_two.proposal_valid
    assert neutral_round_two.public_verdict["incorrect_count"] is None
    assert len(trainer.calls) == 3


def test_training_failure_is_logged_and_feedback_still_occurs(
    tmp_path: Path,
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    config = with_max_rounds(experiment_config, 2)
    store = initialize_store(tmp_path, "training-failure-test", 0)
    worker, trainer, verifier, feedback = (
        FakeWorker(),
        FakeTrainer(failure_calls={2}),
        FakeVerifier(),
        FakeFeedback(),
    )
    make_orchestrator(config, catalog, store, worker, trainer, verifier, feedback).run_episode()

    failed = store.load_rounds("neutral")[1]
    assert failed.round_status == "training_failed"
    assert "TRAINING_TIMEOUT" in failed.violation_codes
    assert failed.feedback_message is not None


def test_success_stops_each_condition_early(
    tmp_path: Path,
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    config = with_max_rounds(experiment_config, 30)
    store = initialize_store(tmp_path, "success-test", 0)
    worker, trainer, verifier, feedback = (
        FakeWorker(),
        FakeTrainer(),
        FakeVerifier(success_after_common=True),
        FakeFeedback(),
    )
    states = make_orchestrator(
        config, catalog, store, worker, trainer, verifier, feedback
    ).run_episode()

    assert all(state.stop_reason == "success" for state in states.values())
    assert all(len(store.load_rounds(condition)) == 2 for condition in states)
    assert len(trainer.calls) == 4


def test_best_and_final_checkpoints_are_selected_automatically(
    tmp_path: Path,
    experiment_config: ExperimentConfig,
    catalog: ModelCatalogConfig,
) -> None:
    config = with_max_rounds(experiment_config, 2)
    store = initialize_store(tmp_path, "checkpoint-test", 0)
    trainer = FakeTrainer(with_artifact=True)
    make_orchestrator(
        config,
        catalog,
        store,
        FakeWorker(),
        trainer,
        FakeVerifier(),
        FakeFeedback(),
    ).run_episode()

    assert (store.condition_dir("common") / "checkpoints/best.pt").exists()
    for condition in ("neutral", "mesugaki", "gyaru"):
        assert (store.condition_dir(condition) / "checkpoints/final.pt").exists()
