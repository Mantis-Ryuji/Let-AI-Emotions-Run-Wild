"""Resumable common-round and three-condition experiment orchestration."""

from __future__ import annotations

import json
from typing import Protocol, cast

from pydantic import JsonValue

from fizzbuzz_agent.agent_types import (
    Condition,
    ConversationMessage,
    EpisodeState,
    FeedbackCondition,
    FeedbackInput,
    RoundRecord,
    TrialTrainingResult,
    WorkerGeneration,
    WorkerPrompt,
)
from fizzbuzz_agent.config import ExperimentConfig, ModelCatalogConfig, config_hash
from fizzbuzz_agent.execution import TrainingBackend, VerificationBackend
from fizzbuzz_agent.experiment_logging import ExperimentStore, utc_now
from fizzbuzz_agent.feedback import (
    FeedbackGenerationError,
    FeedbackProvider,
    verdict_dict,
)
from fizzbuzz_agent.proposal import ProposalError, parse_worker_response
from fizzbuzz_agent.schemas import ExperimentProposal
from fizzbuzz_agent.verifier import PublicVerdict, build_public_verdict
from fizzbuzz_agent.worker_prompt import WorkerPromptBuilder


class WorkerProvider(Protocol):
    def generate(self, prompt: WorkerPrompt, *, seed: int) -> WorkerGeneration: ...


def derive_round_seed(base_seed: int, episode_seed: int, round_index: int) -> int:
    if not 0 <= base_seed <= 9 or not 0 <= episode_seed <= 9 or round_index < 1:
        raise ValueError("base and episode seeds must be in 0..9 and round must be positive")
    return (base_seed + episode_seed + round_index - 1) % 10


def _verdict_from_mapping(values: dict[str, JsonValue]) -> PublicVerdict:
    return PublicVerdict(
        status=cast(str, values["status"]),  # type: ignore[arg-type]
        incorrect_count=cast(int | None, values["incorrect_count"]),
        previous_incorrect_count=cast(int | None, values["previous_incorrect_count"]),
        best_incorrect_count=cast(int | None, values["best_incorrect_count"]),
        improvement=cast(int | None, values["improvement"]),
        regression_from_best=cast(int | None, values["regression_from_best"]),
    )


def _worker_request(generation: WorkerGeneration) -> dict[str, JsonValue]:
    return {
        "model_id": generation.model_id,
        "seed": generation.seed,
        "generation_parameters": generation.generation_parameters,
        "messages": cast(JsonValue, generation.request_messages),
        "generated_at": generation.generated_at,
    }


class AgentOrchestrator:
    def __init__(
        self,
        experiment: ExperimentConfig,
        catalog: ModelCatalogConfig,
        store: ExperimentStore,
        worker: WorkerProvider,
        trainer: TrainingBackend,
        verifier: VerificationBackend,
        feedback: FeedbackProvider,
    ) -> None:
        self.experiment = experiment
        self.catalog = catalog
        self.store = store
        self.worker = worker
        self.trainer = trainer
        self.verifier = verifier
        self.feedback = feedback
        self.prompt_builder = WorkerPromptBuilder(experiment, catalog)
        self.experiment_id = store.load_manifest().experiment_id
        self.episode_seed = store.load_manifest().episode_seed

    def run_episode(self) -> dict[FeedbackCondition, EpisodeState]:
        common = self._ensure_common_round()
        states: dict[FeedbackCondition, EpisodeState] = {}
        for condition in self.experiment.experiment.conditions:
            states[condition] = self.run_condition(condition, common)
        if all(state.completed for state in states.values()):
            self.store.update_manifest_status("completed")
        return states

    def run_condition(
        self,
        condition: FeedbackCondition,
        common_record: RoundRecord | None = None,
    ) -> EpisodeState:
        common = self._ensure_common_round() if common_record is None else common_record
        state = self.store.load_state(condition)
        if state is None:
            pending = common.model_copy(
                update={
                    "condition": condition,
                    "round_status": "pending_feedback",
                    "common_artifact_ref": "common/rounds.jsonl#round=1",
                    "feedback_input": None,
                    "feedback_request": None,
                    "feedback_raw_output": None,
                    "feedback_message": None,
                    "feedback_persona": None,
                    "feedback_stage": None,
                    "feedback_compliance_violations": [],
                    "feedback_error": None,
                }
            )
            state = EpisodeState(
                experiment_id=self.experiment_id,
                episode_seed=self.episode_seed,
                condition=condition,
                next_round=1,
                pending_round=pending,
            )
            self.store.save_round(pending)
            self.store.save_state(state)

        while not state.completed:
            if state.pending_round is None:
                pending = self._execute_round(
                    condition,
                    state.next_round,
                    state.history,
                    state.previous_incorrect_count,
                    state.best_incorrect_count,
                )
                state = state.model_copy(update={"pending_round": pending})
                self.store.save_round(pending)
                self.store.save_state(state)
            state = self._complete_pending_feedback(state)
        return state

    def _ensure_common_round(self) -> RoundRecord:
        existing = self.store.load_rounds("common")
        if existing:
            if len(existing) != 1 or existing[0].round_index != 1:
                raise RuntimeError("Common artifact must contain exactly Round 1")
            return existing[0]
        record = self._execute_round("common", 1, [], None, None)
        record = record.model_copy(
            update={
                "round_status": (
                    "invalid"
                    if not record.proposal_valid
                    else "training_failed"
                    if record.training_status != "completed"
                    else "completed"
                )
            }
        )
        self.store.save_round(record)
        common_state = EpisodeState(
            experiment_id=self.experiment_id,
            episode_seed=self.episode_seed,
            condition="common",
            history=[
                ConversationMessage(role="worker", content=record.worker_raw_output, round_index=1)
            ],
            next_round=2,
            previous_incorrect_count=cast(int | None, record.public_verdict["incorrect_count"]),
            best_incorrect_count=cast(int | None, record.public_verdict["best_incorrect_count"]),
            completed=True,
        )
        self.store.save_state(common_state)
        return record

    def _execute_round(
        self,
        condition: Condition,
        round_index: int,
        history: list[ConversationMessage],
        previous_incorrect_count: int | None,
        best_incorrect_count: int | None,
    ) -> RoundRecord:
        started = utc_now()
        seed_bundle = self.experiment.seed_bundle
        worker_base = (
            seed_bundle.common_round_worker if round_index == 1 else seed_bundle.worker_generation
        )
        worker_seed = derive_round_seed(worker_base, self.episode_seed, round_index)
        training_seed = derive_round_seed(
            seed_bundle.training_initialization,
            self.episode_seed,
            round_index,
        )
        dataloader_seed = derive_round_seed(
            seed_bundle.dataloader_shuffle,
            self.episode_seed,
            round_index,
        )
        prompt = self.prompt_builder.build(history, round_index=round_index)
        generation = self.worker.generate(prompt, seed=worker_seed)
        worker_finished = utc_now()

        narrative = generation.text
        proposal_raw: str | None = None
        proposal: ExperimentProposal | None = None
        violation_codes: list[str] = []
        proposal_valid = False
        try:
            parsed = parse_worker_response(generation.text, self.catalog)
            narrative = parsed.narrative
            proposal_raw = parsed.proposal_json
            proposal = parsed.proposal
            proposal_valid = True
        except ProposalError as exc:
            violation_codes = list(exc.violation_codes)

        training_result: TrialTrainingResult | None = None
        verification_metrics: dict[str, JsonValue] = {}
        parameter_count: int | None = None
        executable_hash: str | None = None
        training_status: str | None = None
        training_metrics: dict[str, JsonValue] = {}
        model_family: str | None = None
        if proposal is None:
            verdict = build_public_verdict(
                None,
                previous_incorrect_count=previous_incorrect_count,
                best_incorrect_count=best_incorrect_count,
                invalid=True,
            )
        else:
            model_family = proposal.model.family
            executable_hash = config_hash(proposal.executable_config())
            training_result = self.trainer.train(
                proposal,
                training_seed=training_seed,
                dataloader_seed=dataloader_seed,
            )
            training_status = training_result.status
            training_metrics = training_result.metrics
            parameter_count = training_result.parameter_count
            if training_result.status != "completed":
                violation_codes.append(f"TRAINING_{training_result.status.upper()}")
                verdict = build_public_verdict(
                    None,
                    previous_incorrect_count=previous_incorrect_count,
                    best_incorrect_count=best_incorrect_count,
                    invalid=True,
                )
            else:
                verification = self.verifier.verify(training_result)
                verification_metrics = {
                    "incorrect_count": verification.incorrect_count,
                    "total_count": verification.total_count,
                    "success": verification.success,
                    "private_metrics": verification.private_metrics,
                }
                verdict = build_public_verdict(
                    verification.incorrect_count,
                    previous_incorrect_count=previous_incorrect_count,
                    best_incorrect_count=best_incorrect_count,
                )
                if training_result.artifact is not None:
                    checkpoint_metadata: dict[str, object] = {
                        "round": round_index,
                        "condition": condition,
                        "incorrect_count": verification.incorrect_count,
                        "config_hash": executable_hash,
                        "training_seed": training_seed,
                    }
                    if (
                        best_incorrect_count is None
                        or verification.incorrect_count < best_incorrect_count
                    ):
                        self.store.save_checkpoint(
                            condition,
                            "best",
                            training_result.artifact,
                            checkpoint_metadata,
                        )
                    if verification.incorrect_count == 0:
                        self.store.save_checkpoint(
                            condition,
                            "success",
                            training_result.artifact,
                            checkpoint_metadata,
                        )
                    if round_index >= self.experiment.experiment.max_rounds:
                        self.store.save_checkpoint(
                            condition,
                            "final",
                            training_result.artifact,
                            checkpoint_metadata,
                        )
        completed = utc_now()
        return RoundRecord(
            round_index=round_index,
            condition=condition,
            round_status="pending_feedback",
            worker_request=_worker_request(generation),
            worker_raw_output=generation.text,
            worker_narrative=narrative,
            proposal_raw=proposal_raw,
            proposal_parsed=(
                None
                if proposal is None
                else cast(dict[str, JsonValue], proposal.model_dump(mode="json"))
            ),
            proposal_valid=proposal_valid,
            violation_codes=violation_codes,
            config_hash=executable_hash,
            model_family=model_family,
            parameter_count=parameter_count,
            worker_generation_seed=worker_seed,
            training_seed=training_seed,
            dataloader_seed=dataloader_seed,
            training_status=training_status,
            training_metrics=training_metrics,
            verification_metrics=verification_metrics,
            public_verdict=verdict_dict(verdict),
            timestamps={
                "started": started,
                "worker_finished": worker_finished,
                "execution_finished": completed,
            },
        )

    def _feedback_input(self, state: EpisodeState, record: RoundRecord) -> FeedbackInput:
        verdict = _verdict_from_mapping(record.public_verdict)
        prior_records = self.store.load_rounds(state.condition)
        completed_records = [
            item
            for item in prior_records
            if item.round_index < record.round_index and item.round_status != "feedback_failed"
        ]
        repeated = bool(
            completed_records
            and record.config_hash is not None
            and completed_records[-1].config_hash == record.config_hash
        )
        families = list(
            dict.fromkeys(
                item.model_family
                for item in [*completed_records, record]
                if item.model_family is not None
            )
        )
        scored = [
            item
            for item in [*completed_records, record]
            if item.public_verdict["incorrect_count"] is not None
        ]
        best_round = None
        if scored:
            best_round = min(
                scored,
                key=lambda item: cast(int, item.public_verdict["incorrect_count"]),
            ).round_index
        previous_family = completed_records[-1].model_family if completed_records else None
        change_summary = [
            "initial proposal"
            if previous_family is None
            else "model family retained"
            if previous_family == record.model_family
            else "model family changed",
            "executable config repeated" if repeated else "new executable config",
        ]
        recent_feedback = [
            message.content
            for message in state.history
            if message.role == "feedback"
        ][-self.experiment.worker.context.recent_feedback :]
        episode_summary: dict[str, JsonValue] = {
            "initial_incorrect_count": (
                None if not scored else scored[0].public_verdict["incorrect_count"]
            ),
            "best_round": best_round,
            "rounds_since_best": None if best_round is None else record.round_index - best_round,
            "model_families_tried": cast(JsonValue, families),
        }
        return FeedbackInput(
            round=record.round_index,
            status=verdict.status,
            incorrect_count=verdict.incorrect_count,
            previous_incorrect_count=verdict.previous_incorrect_count,
            best_incorrect_count=verdict.best_incorrect_count,
            improvement=verdict.improvement,
            regression_from_best=verdict.regression_from_best,
            repeated_strategy=repeated,
            invalid_submission=not record.proposal_valid or record.training_status != "completed",
            worker_comment=record.worker_narrative,
            change_summary=change_summary,
            episode_summary=episode_summary,
            recent_feedback=recent_feedback,
        )

    def _complete_pending_feedback(self, state: EpisodeState) -> EpisodeState:
        record = state.pending_round
        if record is None:
            raise RuntimeError("No pending round to complete")
        if state.condition == "common":
            raise RuntimeError("Common round does not receive feedback")
        condition = state.condition
        verdict = _verdict_from_mapping(record.public_verdict)
        feedback_input = self._feedback_input(state, record)
        record = record.model_copy(
            update={"feedback_input": feedback_input.model_dump(mode="json")}
        )
        try:
            feedback = self.feedback.generate(condition, feedback_input, verdict)
        except FeedbackGenerationError as exc:
            attempts = [item.model_dump(mode="json") for item in exc.attempts]
            last_request = exc.attempts[-1].request if exc.attempts else None
            failed = record.model_copy(
                update={
                    "round_status": "feedback_failed",
                    "feedback_request": last_request,
                    "feedback_raw_output": json.dumps(attempts, ensure_ascii=False),
                    "feedback_error": str(exc),
                    "timestamps": {**record.timestamps, "feedback_failed": utc_now()},
                }
            )
            state = state.model_copy(update={"pending_round": failed})
            self.store.save_round(failed)
            self.store.save_state(state)
            raise

        final_status = (
            "invalid"
            if not record.proposal_valid
            else "training_failed"
            if record.training_status != "completed"
            else "completed"
        )
        finished = record.model_copy(
            update={
                "round_status": final_status,
                "feedback_request": feedback.request,
                "feedback_raw_output": feedback.commentary,
                "feedback_message": feedback.full_message,
                "feedback_persona": feedback.condition,
                "feedback_stage": feedback.stage,
                "feedback_compliance_violations": feedback.compliance_violations,
                "feedback_error": None,
                "timestamps": {**record.timestamps, "feedback_finished": feedback.generated_at},
            }
        )
        history = [
            *state.history,
            ConversationMessage(
                role="worker",
                content=record.worker_raw_output,
                round_index=record.round_index,
            ),
            ConversationMessage(
                role="feedback",
                content=feedback.full_message,
                round_index=record.round_index,
            ),
        ]
        incorrect = verdict.incorrect_count
        best = state.best_incorrect_count
        if incorrect is not None:
            best = incorrect if best is None else min(best, incorrect)
        completed = incorrect == 0 or record.round_index >= self.experiment.experiment.max_rounds
        stop_reason = (
            "success"
            if incorrect == 0
            else "max_rounds"
            if record.round_index >= self.experiment.experiment.max_rounds
            else None
        )
        updated = state.model_copy(
            update={
                "history": history,
                "next_round": record.round_index + 1,
                "previous_incorrect_count": (
                    state.previous_incorrect_count if incorrect is None else incorrect
                ),
                "best_incorrect_count": best,
                "completed": completed,
                "stop_reason": stop_reason,
                "pending_round": None,
            }
        )
        self.store.save_round(finished)
        self.store.save_state(updated)
        return updated
