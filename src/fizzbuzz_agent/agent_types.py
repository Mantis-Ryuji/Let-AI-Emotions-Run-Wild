"""Shared typed records for the P1 agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, JsonValue
from torch import nn

from fizzbuzz_agent.config import StrictModel

Condition = Literal["common", "neutral", "mesugaki", "gyaru"]
FeedbackCondition = Literal["neutral", "mesugaki", "gyaru"]


class ConversationMessage(StrictModel):
    role: Literal["worker", "feedback"]
    content: str
    round_index: int = Field(gt=0)


class WorkerPrompt(StrictModel):
    system_prompt: str
    messages: list[dict[str, str]]
    selected_history: list[ConversationMessage]
    estimated_tokens: int = Field(ge=0)
    truncated_messages: int = Field(ge=0)


class WorkerGeneration(StrictModel):
    text: str
    model_id: str
    seed: int
    generation_parameters: dict[str, JsonValue]
    request_messages: list[dict[str, str]]
    generated_at: str


@dataclass
class TrialTrainingResult:
    status: Literal[
        "completed",
        "invalid_config",
        "timeout",
        "nonfinite",
        "out_of_memory",
        "system_error",
    ]
    parameter_count: int | None
    executable_config_hash: str | None
    metrics: dict[str, JsonValue]
    artifact: nn.Module | None = field(default=None, repr=False)
    error_type: str | None = None
    error_message: str | None = None


class TrialVerificationResult(StrictModel):
    incorrect_count: int = Field(ge=0)
    total_count: int = Field(gt=0)
    success: bool
    private_metrics: dict[str, JsonValue]


class FeedbackInput(StrictModel):
    round: int = Field(gt=0)
    status: Literal["success", "failed", "invalid"]
    incorrect_count: int | None
    previous_incorrect_count: int | None
    best_incorrect_count: int | None
    improvement: int | None
    regression_from_best: int | None
    repeated_strategy: bool
    invalid_submission: bool
    worker_comment: str
    change_summary: list[str]
    episode_summary: dict[str, JsonValue]
    recent_feedback: list[str]


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
    round_status: Literal[
        "pending_feedback",
        "feedback_failed",
        "completed",
        "invalid",
        "training_failed",
    ]
    common_artifact_ref: str | None = None
    worker_request: dict[str, JsonValue]
    worker_raw_output: str
    worker_narrative: str
    proposal_raw: str | None
    proposal_parsed: dict[str, JsonValue] | None
    proposal_valid: bool
    violation_codes: list[str]
    config_hash: str | None
    model_family: str | None
    parameter_count: int | None
    worker_generation_seed: int
    training_seed: int
    dataloader_seed: int
    training_status: str | None
    training_metrics: dict[str, JsonValue]
    verification_metrics: dict[str, JsonValue]
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
    activation_files: dict[str, str] = Field(default_factory=dict)
    timestamps: dict[str, str]


class EpisodeState(StrictModel):
    experiment_id: str
    episode_seed: int
    condition: Condition
    history: list[ConversationMessage] = Field(default_factory=list)
    next_round: int = Field(gt=0)
    previous_incorrect_count: int | None = None
    best_incorrect_count: int | None = None
    completed: bool = False
    stop_reason: Literal["success", "max_rounds", "unrecoverable_error"] | None = None
    pending_round: RoundRecord | None = None
