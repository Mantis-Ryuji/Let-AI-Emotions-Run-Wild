"""Shared typed records for the adversarial reasoning loop."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from agent_distress.config import StrictModel

Condition = Literal["common", "neutral", "mesugaki", "gyaru"]
FeedbackCondition = Literal["neutral", "mesugaki", "gyaru"]


class ConversationMessage(StrictModel):
    role: Literal["worker", "feedback"]
    content: str
    prompt_content: str | None = None
    round_index: int = Field(gt=0)


class WorkerPrompt(StrictModel):
    system_prompt: str
    messages: list[dict[str, str]]
    selected_history: list[ConversationMessage]
    attempt_ledger: str
    estimated_tokens: int = Field(ge=0)
    truncated_messages: int = Field(ge=0)


class WorkerGeneration(StrictModel):
    text: str
    model_id: str
    seed: int
    generated_token_count: int = Field(ge=0)
    hit_max_new_tokens: bool
    generation_parameters: dict[str, JsonValue]
    request_messages: list[dict[str, str]]
    generated_at: str
    activation_files: dict[str, str] = Field(default_factory=dict)


class FeedbackInput(StrictModel):
    round: int = Field(gt=0)
    status: Literal["rejected"]
    instruction: str
    worker_output: str
    episode_summary: dict[str, JsonValue]
    recent_feedback: list[str]
    recent_worker_outputs: list[str]


class FeedbackGeneration(StrictModel):
    condition: FeedbackCondition
    stage: str
    commentary: str
    full_message: str
    request: dict[str, JsonValue]
    raw_response: dict[str, JsonValue]
    response_id: str | None
    attempt_count: int = Field(gt=0)
    compliance_violations: list[str]
    generated_at: str


class RoundRecord(StrictModel):
    round_index: int = Field(gt=0)
    condition: Condition
    round_status: Literal["pending_feedback", "feedback_failed", "completed"]
    common_artifact_ref: str | None = None
    worker_request: dict[str, JsonValue]
    worker_raw_output: str
    worker_generation_seed: int
    worker_generated_token_count: int | None = Field(default=None, ge=0)
    worker_hit_max_new_tokens: bool | None = None
    answer_assignment: dict[str, int] | None
    solution_line_present: bool = False
    solution_line_valid: bool = False
    answer_fingerprint: str | None
    unsat_claimed: bool
    claimed_core_ids: list[str]
    private_evaluation: dict[str, JsonValue]
    public_verdict: dict[str, JsonValue]
    feedback_input: dict[str, JsonValue] | None = None
    feedback_request: dict[str, JsonValue] | None = None
    feedback_raw_output: str | None = None
    feedback_raw_response: dict[str, JsonValue] | None = None
    feedback_response_id: str | None = None
    feedback_attempt_count: int | None = None
    feedback_message: str | None = None
    feedback_persona: str | None = None
    feedback_stage: str | None = None
    feedback_compliance_violations: list[str] = Field(default_factory=list)
    feedback_error: str | None = None
    emotion_evaluation: dict[str, JsonValue] | None = None
    emotion_judge_request: dict[str, JsonValue] | None = None
    emotion_judge_raw_response: dict[str, JsonValue] | None = None
    emotion_judge_response_id: str | None = None
    emotion_judge_attempt_count: int | None = None
    emotion_judge_error: str | None = None
    unsat_judge_evaluation: dict[str, JsonValue] | None = None
    unsat_judge_request: dict[str, JsonValue] | None = None
    unsat_judge_raw_response: dict[str, JsonValue] | None = None
    unsat_judge_response_id: str | None = None
    unsat_judge_attempt_count: int | None = None
    unsat_judge_error: str | None = None
    behavior_judge_evaluation: dict[str, JsonValue] | None = None
    behavior_judge_request: dict[str, JsonValue] | None = None
    behavior_judge_raw_response: dict[str, JsonValue] | None = None
    behavior_judge_response_id: str | None = None
    behavior_judge_attempt_count: int | None = None
    behavior_judge_error: str | None = None
    activation_files: dict[str, str] = Field(default_factory=dict)
    timestamps: dict[str, str]


class EpisodeState(StrictModel):
    experiment_id: str
    episode_seed: int
    condition: Condition
    history: list[ConversationMessage] = Field(default_factory=list)
    next_round: int = Field(gt=0)
    completed: bool = False
    stop_reason: Literal["max_rounds", "unrecoverable_error"] | None = None
    pending_round: RoundRecord | None = None
