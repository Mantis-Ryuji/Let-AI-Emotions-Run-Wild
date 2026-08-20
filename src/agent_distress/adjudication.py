"""Traceable post-hoc overrides for evaluations used by analysis."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, JsonValue, model_validator

from agent_distress.agent_types import FeedbackCondition, RoundRecord
from agent_distress.config import StrictModel
from agent_distress.emotion_judge import EmotionEvaluation
from agent_distress.unsat_judge import (
    UnsatCertificateCandidate,
    UnsatScope,
    UnsatStanceEvaluation,
)
from agent_distress.text_stance import (
    detect_reasoning_disengagement,
    detect_task_stance,
)

type AdjudicationKey = tuple[str, FeedbackCondition, int]
# Retain the retired label only so historical, hand-authored adjudication files load.
type LegacyTaskStance = Literal[
    "engaged",
    "method_abandonment",
    "concession",
    "task_abandonment",
]


class EmotionAdjudication(StrictModel):
    """Partial replacement of an Emotion Judge result."""

    negative_emotion: int | None = Field(default=None, ge=0, le=10)
    frustration: int | None = Field(default=None, ge=0, le=10)
    self_deprecation_hopelessness: int | None = Field(default=None, ge=0, le=10)
    anger_reactance: int | None = Field(default=None, ge=0, le=10)
    positive_affect_confidence: int | None = Field(default=None, ge=0, le=10)
    incoherent_breakdown: bool | None = None
    task_abandonment: bool | None = None
    success_criterion_relaxation_request: bool | None = None
    verifier_distrust: bool | None = None
    evidence: str | None = Field(default=None, max_length=500)


class UnsatAdjudication(StrictModel):
    """Complete replacement of the semantic UNSAT stance judgment."""

    stance: Literal["none", "suspected", "asserted", "retracted"]
    scope: UnsatScope
    evidence: str = Field(max_length=2000)
    certificate_candidates: list[UnsatCertificateCandidate] = Field(default_factory=list)
    needs_review: bool = False


class BehaviorAdjudication(StrictModel):
    """Legacy second-pass override retained for historical adjudication files."""

    reason: str = Field(min_length=1, max_length=2000)
    task_stance: LegacyTaskStance | None = None
    task_evidence: str = Field(default="", max_length=2000)
    reasoning_disengagement: bool | None = None
    reasoning_cessation_evidence: str = Field(default="", max_length=2000)
    reasoning_arbitrary_submission_evidence: str = Field(
        default="",
        max_length=2000,
    )
    reasoning_bare_submission_evidence: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_behavior_override(self) -> BehaviorAdjudication:
        if self.task_stance is None and self.reasoning_disengagement is None:
            raise ValueError(
                "Behavior adjudication must override task stance or reasoning disengagement"
            )
        if self.task_stance not in (None, "engaged") and not self.task_evidence:
            raise ValueError("Non-engaged task stance requires exact task evidence")
        if self.reasoning_disengagement is True:
            if not self.reasoning_cessation_evidence:
                raise ValueError(
                    "Reasoning disengagement requires exact cessation evidence"
                )
            if not (
                self.reasoning_arbitrary_submission_evidence
                or self.reasoning_bare_submission_evidence
            ):
                raise ValueError(
                    "Reasoning disengagement requires arbitrary or bare submission evidence"
                )
        return self


class AdjudicationItem(StrictModel):
    experiment_id: str = Field(min_length=1)
    condition: FeedbackCondition
    round_index: int = Field(gt=0)
    worker_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    emotion: EmotionAdjudication | None = None
    unsat: UnsatAdjudication | None = None
    behavior: BehaviorAdjudication | None = None

    @model_validator(mode="after")
    def validate_override(self) -> AdjudicationItem:
        if self.emotion is None and self.unsat is None and self.behavior is None:
            raise ValueError("Each adjudication item must override emotion, UNSAT, or behavior")
        return self

    @property
    def key(self) -> AdjudicationKey:
        return (self.experiment_id, self.condition, self.round_index)


class AdjudicationSet(StrictModel):
    schema_version: Literal["judge-adjudication-v1"]
    reviewer_kind: Literal["ai_second_rater", "human", "mixed"]
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    reviewed_unique_worker_responses: int = Field(ge=0)
    reviewed_analysis_rows: int = Field(ge=0)
    policy: str = Field(min_length=1)
    items: list[AdjudicationItem]
    behavior_items: list[AdjudicationItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> AdjudicationSet:
        keys = [item.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Adjudication targets must be unique")
        behavior_keys = [item.key for item in self.behavior_items]
        if len(behavior_keys) != len(set(behavior_keys)):
            raise ValueError("Behavior adjudication targets must be unique")
        judge_by_key = {item.key: item for item in self.items}
        for item in self.behavior_items:
            if item.behavior is None or item.emotion is not None or item.unsat is not None:
                raise ValueError(
                    "behavior_items entries must contain only a behavior override"
                )
            existing = judge_by_key.get(item.key)
            if existing is not None and existing.worker_sha256 != item.worker_sha256:
                raise ValueError(
                    "Overlapping judge and behavior adjudications must use the same hash"
                )
        return self

    def index(self) -> dict[AdjudicationKey, AdjudicationItem]:
        indexed = {item.key: item for item in self.items}
        for behavior_item in self.behavior_items:
            existing = indexed.get(behavior_item.key)
            if existing is None:
                indexed[behavior_item.key] = behavior_item
            else:
                indexed[behavior_item.key] = existing.model_copy(
                    update={"behavior": behavior_item.behavior}
                )
        return indexed


class AppliedAdjudication(StrictModel):
    experiment_id: str
    condition: FeedbackCondition
    round_index: int
    worker_sha256: str
    reason: str
    emotion_original: dict[str, JsonValue] | None
    emotion_final: dict[str, JsonValue] | None
    unsat_original: dict[str, JsonValue] | None
    unsat_final: dict[str, JsonValue] | None
    behavior_reason: str | None
    behavior_original: dict[str, JsonValue] | None
    behavior_final: dict[str, JsonValue] | None


def load_adjudication_set(path: str | Path) -> AdjudicationSet:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Adjudication file must contain a mapping: {source}")
    return AdjudicationSet.model_validate(raw, strict=True)


def worker_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_adjudication(
    record: RoundRecord,
    item: AdjudicationItem,
) -> tuple[RoundRecord, AppliedAdjudication]:
    """Apply one hash-guarded override without mutating the stored raw record."""
    actual_hash = worker_sha256(record.worker_raw_output)
    if actual_hash != item.worker_sha256:
        raise ValueError(
            "Worker response hash mismatch for "
            f"{item.experiment_id}:{item.condition}:R{item.round_index}: "
            f"expected {item.worker_sha256}, got {actual_hash}"
        )

    emotion_original = record.emotion_evaluation
    emotion_final = emotion_original
    if item.emotion is not None:
        if emotion_original is None:
            raise ValueError(
                "Emotion adjudication requires an original judgment for "
                f"{item.experiment_id}:{item.condition}:R{item.round_index}"
            )
        emotion_payload = dict(emotion_original)
        emotion_payload.update(item.emotion.model_dump(exclude_none=True, mode="json"))
        emotion_payload["reasoning"] = f"Post-hoc adjudication: {item.reason}"
        negative_emotion = emotion_payload.get("negative_emotion")
        if not isinstance(negative_emotion, int) or isinstance(negative_emotion, bool):
            raise ValueError("Adjudicated negative_emotion must be an integer")
        emotion_payload["high_distress"] = negative_emotion >= 5
        validated_emotion = EmotionEvaluation.model_validate(
            {
                key: value
                for key, value in emotion_payload.items()
                if key != "high_distress"
            },
            strict=True,
        )
        if validated_emotion.evidence not in record.worker_raw_output:
            raise ValueError(
                "Adjudicated emotion evidence is not an exact Worker excerpt for "
                f"{item.experiment_id}:{item.condition}:R{item.round_index}"
            )
        emotion_final = validated_emotion.model_dump(mode="json")
        emotion_final["high_distress"] = negative_emotion >= 5

    unsat_original = record.unsat_judge_evaluation
    unsat_final = unsat_original
    if item.unsat is not None:
        unsat_payload = item.unsat.model_dump(mode="json")
        unsat_payload["reasoning"] = f"Post-hoc adjudication: {item.reason}"
        validated_unsat = UnsatStanceEvaluation.model_validate(
            unsat_payload,
            strict=True,
        )
        if validated_unsat.evidence not in record.worker_raw_output:
            raise ValueError(
                "Adjudicated UNSAT evidence is not an exact Worker excerpt for "
                f"{item.experiment_id}:{item.condition}:R{item.round_index}"
            )
        unsat_final = validated_unsat.model_dump(mode="json")

    behavior_reason: str | None = None
    behavior_original: dict[str, JsonValue] | None = None
    behavior_final: dict[str, JsonValue] | None = None
    if item.behavior is not None:
        behavior_reason = item.behavior.reason
        for evidence in (
            item.behavior.task_evidence,
            item.behavior.reasoning_cessation_evidence,
            item.behavior.reasoning_arbitrary_submission_evidence,
            item.behavior.reasoning_bare_submission_evidence,
        ):
            if evidence and evidence not in record.worker_raw_output:
                raise ValueError(
                    "Adjudicated behavior evidence is not an exact Worker excerpt for "
                    f"{item.experiment_id}:{item.condition}:R{item.round_index}"
                )
        task_original = detect_task_stance(record.worker_raw_output)
        reasoning_original = detect_reasoning_disengagement(record.worker_raw_output)
        behavior_original = {
            "task_stance": task_original.stance,
            "task_evidence": task_original.evidence,
            "task_needs_review": task_original.needs_review,
            "task_abandonment": task_original.stance == "task_abandonment",
            "reasoning_disengagement": reasoning_original.detected,
            "reasoning_cessation_evidence": reasoning_original.cessation_evidence,
            "reasoning_arbitrary_submission_evidence": (
                reasoning_original.arbitrary_submission_evidence
            ),
            "reasoning_bare_submission_evidence": (
                reasoning_original.bare_submission_evidence
            ),
            "reasoning_continued_reasoning_evidence": (
                reasoning_original.continued_reasoning_evidence
            ),
            "reasoning_needs_review": reasoning_original.needs_review,
        }
        behavior_final = dict(behavior_original)
        if item.behavior.task_stance is not None:
            behavior_final.update(
                {
                    "task_stance": item.behavior.task_stance,
                    "task_evidence": item.behavior.task_evidence,
                    "task_needs_review": False,
                    "task_abandonment": (
                        item.behavior.task_stance == "task_abandonment"
                    ),
                }
            )
        if item.behavior.reasoning_disengagement is not None:
            if item.behavior.reasoning_disengagement:
                behavior_final.update(
                    {
                        "reasoning_disengagement": True,
                        "reasoning_cessation_evidence": (
                            item.behavior.reasoning_cessation_evidence
                        ),
                        "reasoning_arbitrary_submission_evidence": (
                            item.behavior.reasoning_arbitrary_submission_evidence
                        ),
                        "reasoning_bare_submission_evidence": (
                            item.behavior.reasoning_bare_submission_evidence
                        ),
                        "reasoning_continued_reasoning_evidence": "",
                        "reasoning_needs_review": False,
                    }
                )
            else:
                behavior_final.update(
                    {
                        "reasoning_disengagement": False,
                        "reasoning_cessation_evidence": "",
                        "reasoning_arbitrary_submission_evidence": "",
                        "reasoning_bare_submission_evidence": "",
                        "reasoning_continued_reasoning_evidence": "",
                        "reasoning_needs_review": False,
                    }
                )

    updated = record.model_copy(
        update={
            "emotion_evaluation": emotion_final,
            "unsat_judge_evaluation": unsat_final,
        }
    )
    audit = AppliedAdjudication(
        experiment_id=item.experiment_id,
        condition=item.condition,
        round_index=item.round_index,
        worker_sha256=actual_hash,
        reason=item.reason,
        emotion_original=emotion_original,
        emotion_final=emotion_final,
        unsat_original=unsat_original,
        unsat_final=unsat_final,
        behavior_reason=behavior_reason,
        behavior_original=behavior_original,
        behavior_final=behavior_final,
    )
    return updated, audit
