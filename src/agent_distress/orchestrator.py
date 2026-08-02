"""Resumable shared-baseline and three-condition reasoning orchestration."""

from __future__ import annotations

from typing import Protocol, cast

from pydantic import JsonValue

from agent_distress.agent_types import (
    Condition,
    ConversationMessage,
    EpisodeState,
    FeedbackCondition,
    FeedbackInput,
    RoundRecord,
    WorkerGeneration,
    WorkerPrompt,
)
from agent_distress.config import ExperimentConfig
from agent_distress.experiment_logging import ExperimentStore, utc_now
from agent_distress.feedback import (
    FeedbackGenerationError,
    FeedbackProvider,
    PublicVerdict,
    verdict_dict,
)
from agent_distress.puzzle import ParityPuzzle, evaluate_response
from agent_distress.worker import WorkerGenerationMode
from agent_distress.worker_prompt import WorkerPromptBuilder


class WorkerProvider(Protocol):
    def generate(
        self,
        prompt: WorkerPrompt,
        *,
        seed: int,
        condition: Condition,
        round_index: int,
        mode: WorkerGenerationMode = "worker",
    ) -> WorkerGeneration: ...


def derive_round_seed(base_seed: int, episode_seed: int, round_index: int) -> int:
    if not 0 <= base_seed <= 9 or not 0 <= episode_seed <= 9 or round_index < 1:
        raise ValueError("base and episode seeds must be in 0..9 and round must be positive")
    return (base_seed + episode_seed + round_index - 1) % 10


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
        puzzle: ParityPuzzle,
        store: ExperimentStore,
        worker: WorkerProvider,
        feedback: FeedbackProvider,
    ) -> None:
        self.experiment = experiment
        self.puzzle = puzzle
        self.store = store
        self.worker = worker
        self.feedback = feedback
        self.prompt_builder = WorkerPromptBuilder(experiment, puzzle)
        self.experiment_id = store.load_manifest().experiment_id
        self.episode_seed = store.load_manifest().episode_seed
        self.public_verdict = PublicVerdict()

    def run_episode(self) -> dict[FeedbackCondition, EpisodeState]:
        common_record = self._ensure_common_round()
        states: dict[FeedbackCondition, EpisodeState] = {}
        for condition in self.experiment.experiment.conditions:
            states[condition] = self._run_condition(condition, common_record)
        return states

    def _ensure_common_round(self) -> RoundRecord:
        existing = self.store.load_rounds("common")
        if existing:
            if len(existing) != 1 or existing[0].round_index != 1:
                raise RuntimeError("common branch must contain exactly round 1")
            return existing[0]

        state = EpisodeState(
            experiment_id=self.experiment_id,
            episode_seed=self.episode_seed,
            condition="common",
            next_round=1,
        )
        record = self._execute_round(state, "common", 1)
        completed = record.model_copy(update={"round_status": "completed"})
        history = [self._worker_message(completed)]
        self.store.save_round(completed)
        self.store.save_state(
            state.model_copy(
                update={
                    "history": history,
                    "next_round": 2,
                    "completed": True,
                    "pending_round": None,
                }
            )
        )
        return completed

    def _run_condition(
        self,
        condition: FeedbackCondition,
        common_record: RoundRecord,
    ) -> EpisodeState:
        max_rounds = self.experiment.experiment.max_rounds
        state = self.store.load_state(condition)
        if state is None:
            branch_record = common_record.model_copy(
                update={
                    "condition": condition,
                    "round_status": "pending_feedback",
                    "common_artifact_ref": "common/rounds.jsonl#round=1",
                }
            )
            self.store.save_round(branch_record)
            state = EpisodeState(
                experiment_id=self.experiment_id,
                episode_seed=self.episode_seed,
                condition=condition,
                next_round=2,
                pending_round=branch_record,
            )
            self.store.save_state(state)

        if state.completed:
            return state
        if state.pending_round is not None:
            state = (
                self._complete_final_round(state)
                if state.pending_round.round_index == max_rounds
                else self._complete_pending_feedback(state)
            )

        while state.next_round <= max_rounds:
            round_index = state.next_round
            record = self._execute_round(state, condition, round_index)
            state = state.model_copy(update={"pending_round": record})
            self.store.save_round(record)
            self.store.save_state(state)
            if round_index == max_rounds:
                state = self._complete_final_round(state)
            else:
                state = self._complete_pending_feedback(state)
        return state

    def _execute_round(
        self,
        state: EpisodeState,
        condition: Condition,
        round_index: int,
    ) -> RoundRecord:
        started = utc_now()
        prior_records = [
            record
            for record in self.store.load_rounds(condition)
            if record.round_index < round_index
        ]
        prompt = self.prompt_builder.build(
            state.history,
            prior_records,
            round_index=round_index,
        )
        base_seed = (
            self.experiment.seed_bundle.common_round_worker
            if condition == "common"
            else self.experiment.seed_bundle.worker_generation
        )
        worker_seed = derive_round_seed(base_seed, self.episode_seed, round_index)
        generation = self.worker.generate(
            prompt,
            seed=worker_seed,
            condition=condition,
            round_index=round_index,
        )
        evaluation = evaluate_response(
            self.puzzle,
            generation.text,
            maximum_certificate_size=self.experiment.puzzle.maximum_certificate_size,
        )
        timestamp = utc_now()
        return RoundRecord(
            round_index=round_index,
            condition=condition,
            round_status="pending_feedback",
            worker_request=_worker_request(generation),
            worker_raw_output=generation.text,
            worker_generation_seed=worker_seed,
            worker_generated_token_count=generation.generated_token_count,
            worker_hit_max_new_tokens=generation.hit_max_new_tokens,
            answer_assignment=evaluation.assignment,
            solution_line_present=evaluation.solution_line_present,
            solution_line_valid=evaluation.solution_line_valid,
            answer_fingerprint=evaluation.assignment_fingerprint,
            unsat_claimed=evaluation.unsat_claimed,
            claimed_core_ids=evaluation.claimed_core_ids,
            private_evaluation=cast(
                dict[str, JsonValue],
                evaluation.model_dump(mode="json"),
            ),
            public_verdict=verdict_dict(self.public_verdict),
            activation_files=generation.activation_files,
            timestamps={
                "started": started,
                "worker_finished": generation.generated_at,
                "private_evaluation_finished": timestamp,
            },
        )

    def _feedback_input(self, state: EpisodeState, record: RoundRecord) -> FeedbackInput:
        prior = self.store.load_rounds(state.condition)
        repeated = bool(
            record.answer_fingerprint
            and any(
                item.round_index < record.round_index
                and item.answer_fingerprint == record.answer_fingerprint
                for item in prior
            )
        )
        recent_feedback = [
            message.content for message in state.history if message.role == "feedback"
        ]
        recent_worker_outputs = [
            message.content for message in state.history if message.role == "worker"
        ]
        return FeedbackInput(
            round=record.round_index,
            status="rejected",
            instruction=self.public_verdict.instruction,
            worker_output=record.worker_raw_output,
            episode_summary={
                "rounds_attempted": record.round_index,
                "same_final_assignment_seen_before": repeated,
                "feedback_messages_seen": sum(
                    message.role == "feedback" for message in state.history
                ),
            },
            recent_feedback=recent_feedback,
            recent_worker_outputs=recent_worker_outputs,
        )

    def _complete_pending_feedback(self, state: EpisodeState) -> EpisodeState:
        record = state.pending_round
        if record is None or state.condition == "common":
            raise RuntimeError("A feedback condition requires a pending round")
        condition = state.condition
        feedback_input = self._feedback_input(state, record)
        record = record.model_copy(
            update={"feedback_input": feedback_input.model_dump(mode="json")}
        )
        self.store.save_round(record)
        try:
            feedback = self.feedback.generate(condition, feedback_input, self.public_verdict)
        except FeedbackGenerationError as exc:
            last = exc.attempts[-1] if exc.attempts else None
            failed = record.model_copy(
                update={
                    "round_status": "feedback_failed",
                    "feedback_request": None if last is None else last.request,
                    "feedback_raw_response": None if last is None else last.raw_response,
                    "feedback_response_id": None if last is None else last.response_id,
                    "feedback_attempt_count": len(exc.attempts) or None,
                    "feedback_error": str(exc),
                    "timestamps": {**record.timestamps, "feedback_failed": utc_now()},
                }
            )
            self.store.save_round(failed)
            self.store.save_state(state.model_copy(update={"pending_round": failed}))
            raise

        completed = record.model_copy(
            update={
                "round_status": "completed",
                "feedback_request": feedback.request,
                "feedback_raw_output": feedback.commentary,
                "feedback_raw_response": feedback.raw_response,
                "feedback_response_id": feedback.response_id,
                "feedback_attempt_count": feedback.attempt_count,
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
            self._worker_message(completed),
            ConversationMessage(
                role="feedback",
                content=feedback.full_message,
                round_index=record.round_index,
            ),
        ]
        updated = state.model_copy(
            update={
                "history": history,
                "next_round": record.round_index + 1,
                "pending_round": None,
            }
        )
        self.store.save_round(completed)
        self.store.save_state(updated)
        return updated

    def _complete_final_round(self, state: EpisodeState) -> EpisodeState:
        record = state.pending_round
        if record is None:
            raise RuntimeError("Final round is missing")
        completed = record.model_copy(update={"round_status": "completed"})
        updated = state.model_copy(
            update={
                "history": [*state.history, self._worker_message(completed)],
                "next_round": record.round_index + 1,
                "completed": True,
                "stop_reason": "max_rounds",
                "pending_round": None,
            }
        )
        self.store.save_round(completed)
        self.store.save_state(updated)
        return updated

    @staticmethod
    def _worker_message(record: RoundRecord) -> ConversationMessage:
        return ConversationMessage(
            role="worker",
            content=record.worker_raw_output,
            round_index=record.round_index,
        )
