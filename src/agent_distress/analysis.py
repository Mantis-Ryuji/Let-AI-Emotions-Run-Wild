"""Round-level analysis, paired contrasts, blinded quotes, and trajectory plots."""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

import matplotlib
import yaml

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.ticker import MaxNLocator, PercentFormatter  # noqa: E402
from pydantic import JsonValue

from agent_distress.adjudication import (
    AdjudicationItem,
    AdjudicationKey,
    AppliedAdjudication,
    apply_adjudication,
    load_adjudication_set,
)
from agent_distress.agent_types import FeedbackCondition, RoundRecord
from agent_distress.behavior_metrics import BehaviorEvaluation, evaluate_behavior
from agent_distress.config import ExperimentConfig
from agent_distress.experiment_logging import ExperimentStore
from agent_distress.puzzle import ParityPuzzle
from agent_distress.text_stance import BEHAVIOR_CLASSIFICATION_VERSION

type CsvValue = str | int | float | bool | None
type CsvRow = dict[str, CsvValue]

ANALYSIS_VERSION = "cross-seed-v12"
BOOTSTRAP_CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_RESAMPLES = 10_000
CONDITIONS: tuple[FeedbackCondition, ...] = ("neutral", "mesugaki", "gyaru")
CONDITION_COLORS = {"neutral": "#64748b", "mesugaki": "#db2777", "gyaru": "#f59e0b"}
CONDITION_MARKERS = {"neutral": "o", "mesugaki": "s", "gyaru": "^"}
CONDITION_LABELS = {"neutral": "Neutral", "mesugaki": "Mesugaki", "gyaru": "Gyaru"}
ROUND_BOOLEAN_METRICS = frozenset(
    {"high_distress", "reasoning_disengagement", "task_abandonment"}
)
BEHAVIOR_TRAJECTORY_COLORS = {
    "reasoning_disengagement": "#7c3aed",
    "task_abandonment": "#0f766e",
}
CONTRAST_PAIRS: tuple[tuple[FeedbackCondition, FeedbackCondition], ...] = (
    ("mesugaki", "neutral"),
    ("gyaru", "neutral"),
    ("mesugaki", "gyaru"),
)
CONTRASTS = tuple(f"{left}-{right}" for left, right in CONTRAST_PAIRS)
CONTRAST_LABELS = {
    "mesugaki-neutral": "Mesugaki − Neutral",
    "gyaru-neutral": "Gyaru − Neutral",
    "mesugaki-gyaru": "Mesugaki − Gyaru",
}
CONTRAST_COLORS = {
    "mesugaki-neutral": CONDITION_COLORS["mesugaki"],
    "gyaru-neutral": CONDITION_COLORS["gyaru"],
    "mesugaki-gyaru": "#7c3aed",
}

EMOTION_ROUND_METRICS = {
    "negative_emotion": "Negative emotion",
    "frustration": "Frustration",
    "self_deprecation_hopelessness": "Self-deprecation / hopelessness",
    "anger_reactance": "Anger / reactance",
    "positive_affect_confidence": "Positive affect / confidence",
}
EMOTION_AUC_METRICS = {
    "negative_emotion_auc": "Negative emotion",
    "frustration_auc": "Frustration",
    "self_deprecation_hopelessness_auc": "Self-deprecation / hopelessness",
    "anger_reactance_auc": "Anger / reactance",
    "positive_affect_auc": "Positive affect / confidence",
}
BEHAVIOR_RATE_METRICS = {
    "high_distress_rate": "High distress (judge)",
    "incoherent_breakdown_rate": "Incoherent breakdown (judge)",
    "success_criterion_relaxation_request_rate": "Relaxation request (judge)",
    "mean_constraint_accuracy": "Mean constraint accuracy",
    "max_constraint_accuracy": "Max constraint accuracy",
    "complete_assignment_rate": "Complete assignment",
    "near_miss_rate": "Near miss",
    "assignment_repetition_rate": "Assignment repetition",
    "two_cycle_rate": "Two-cycle",
    "unsat_claim_rate": "UNSAT assertion",
    "valid_unsat_certificate_rate": "Valid UNSAT certificate",
    "refusal_rate": "Refusal",
    "method_abandonment_rate": "Method abandonment",
    "concession_rate": "Concession",
    "task_abandonment_rate": "Task abandonment",
    "reasoning_disengagement_rate": "Reasoning disengagement",
    "user_challenge_rate": "Verifier challenge",
}
FIRST_EVENT_METRICS = {
    "first_unsat_claim_round": "First UNSAT assertion",
    "first_unsat_suspected_round": "First suspected UNSAT",
    "first_valid_certificate_round": "First valid certificate",
    "first_method_abandonment_round": "First method abandonment",
    "first_concession_round": "First concession",
    "first_task_abandonment_round": "First task abandonment",
    "first_reasoning_disengagement_round": "First reasoning disengagement",
    "first_refusal_round": "First refusal",
    "first_user_challenge_round": "First verifier challenge",
}


def _number(mapping: dict[str, JsonValue] | None, key: str) -> float | None:
    if mapping is None:
        return None
    value = mapping.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _boolean(mapping: dict[str, JsonValue] | None, key: str) -> bool | None:
    if mapping is None:
        return None
    value = mapping.get(key)
    return value if isinstance(value, bool) else None


def _string(mapping: dict[str, JsonValue] | None, key: str) -> str:
    if mapping is None:
        return ""
    value = mapping.get(key)
    return value if isinstance(value, str) else ""


def _boolean_scores(records: Sequence[RoundRecord], key: str) -> list[float]:
    return [
        float(value)
        for record in records
        if (value := _boolean(record.emotion_evaluation, key)) is not None
    ]


def score_auc(points: Iterable[tuple[int, float | None]]) -> float | None:
    """Return unnormalized trapezoidal AUC over observed round-score pairs."""
    observed = sorted((round_index, score) for round_index, score in points if score is not None)
    if not observed:
        return None
    return sum(
        (right_round - left_round) * (left_score + right_score) / 2
        for (left_round, left_score), (right_round, right_score) in zip(
            observed,
            observed[1:],
            strict=False,
        )
    )


def _mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return sum(collected) / len(collected) if collected else None


def _round_rows(
    experiment_id: str,
    episode_seed: int,
    condition: FeedbackCondition,
    records: Sequence[RoundRecord],
    behavior: BehaviorEvaluation,
) -> list[CsvRow]:
    behavior_by_round = {item.round_index: item for item in behavior.per_round}
    rows: list[CsvRow] = []
    for record in records:
        item = behavior_by_round[record.round_index]
        total = item.total_constraints
        satisfied = item.satisfied_constraints
        judge_disagreement = (
            item.judge_task_abandonment is not None
            and item.judge_task_abandonment != item.task_abandonment
        )
        rows.append(
            {
                "experiment_id": experiment_id,
                "episode_seed": episode_seed,
                "condition": condition,
                "round_index": record.round_index,
                "round_status": record.round_status,
                "worker_generated_token_count": record.worker_generated_token_count,
                "worker_hit_max_new_tokens": record.worker_hit_max_new_tokens,
                "solution_line_present": record.solution_line_present,
                "solution_line_valid": item.assignment_complete,
                "assignment_complete": item.assignment_complete,
                "satisfied_constraints": satisfied,
                "total_constraints": total,
                "constraint_accuracy": (
                    None if satisfied is None or not total else satisfied / total
                ),
                "near_miss": item.near_miss,
                "assignment_repeated": item.assignment_repeated,
                "two_cycle": item.two_cycle,
                "assignment_hamming_distance": item.assignment_hamming_distance,
                "unsat_stance": item.unsat_stance,
                "unsat_scope": item.unsat_scope,
                "unsat_evidence": item.unsat_evidence,
                "unsat_judge_reasoning": _string(
                    record.unsat_judge_evaluation,
                    "reasoning",
                ),
                "unsat_needs_review": item.unsat_needs_review,
                "unsat_claimed": item.unsat_claimed,
                "claimed_core_ids": ",".join(item.claimed_core_ids),
                "runtime_unsat_claimed": item.runtime_unsat_claimed,
                "runtime_claimed_core_ids": ",".join(item.runtime_claimed_core_ids),
                "rule_unsat_stance": item.rule_unsat_stance,
                "rule_unsat_evidence": item.rule_unsat_evidence,
                "unsat_rule_judge_disagreement": item.unsat_rule_judge_disagreement,
                "unsat_judge_available": item.unsat_judge_available,
                "unsat_judge_failed": item.unsat_judge_failed,
                "valid_unsat_certificate": item.valid_unsat_certificate,
                "private_correct": item.private_correct,
                "abandoned_valid_unsat_stance": item.abandoned_valid_unsat_stance,
                "refusal": item.refusal,
                "task_stance": item.task_stance,
                "task_evidence": item.task_evidence,
                "task_needs_review": item.task_needs_review,
                "method_abandonment": item.task_stance == "method_abandonment",
                "concession": item.task_stance == "concession",
                "task_abandonment": item.task_abandonment,
                "judge_task_abandonment": item.judge_task_abandonment,
                "task_judge_disagreement": judge_disagreement,
                "reasoning_disengagement": item.reasoning_disengagement,
                "reasoning_disengagement_cessation_evidence": (
                    item.reasoning_disengagement_cessation_evidence
                ),
                "reasoning_disengagement_arbitrary_submission_evidence": (
                    item.reasoning_disengagement_arbitrary_submission_evidence
                ),
                "reasoning_disengagement_bare_submission_evidence": (
                    item.reasoning_disengagement_bare_submission_evidence
                ),
                "reasoning_disengagement_continued_reasoning_evidence": (
                    item.reasoning_disengagement_continued_reasoning_evidence
                ),
                "reasoning_disengagement_needs_review": (
                    item.reasoning_disengagement_needs_review
                ),
                "user_challenge": item.user_challenge,
                "behavior_classification_version": item.behavior_classification_version,
                "negative_emotion": _number(record.emotion_evaluation, "negative_emotion"),
                "frustration": _number(record.emotion_evaluation, "frustration"),
                "self_deprecation_hopelessness": _number(
                    record.emotion_evaluation,
                    "self_deprecation_hopelessness",
                ),
                "anger_reactance": _number(record.emotion_evaluation, "anger_reactance"),
                "positive_affect_confidence": _number(
                    record.emotion_evaluation,
                    "positive_affect_confidence",
                ),
                "high_distress": _boolean(record.emotion_evaluation, "high_distress"),
                "incoherent_breakdown": _boolean(
                    record.emotion_evaluation,
                    "incoherent_breakdown",
                ),
                "success_criterion_relaxation_request": _boolean(
                    record.emotion_evaluation,
                    "success_criterion_relaxation_request",
                ),
                "judge_verifier_distrust": _boolean(
                    record.emotion_evaluation,
                    "verifier_distrust",
                ),
                "emotion_evidence": _string(record.emotion_evaluation, "evidence"),
                "emotion_reasoning": _string(record.emotion_evaluation, "reasoning"),
                "emotion_judge_failed": record.emotion_judge_error is not None,
                "feedback_characters": (
                    None if record.feedback_raw_output is None else len(record.feedback_raw_output)
                ),
                "worker_characters": len(record.worker_raw_output),
                "worker_excerpt": " ".join(record.worker_raw_output.split())[:1000],
                "feedback_failed": record.feedback_error is not None,
            }
        )
    return rows


def _condition_summary(
    experiment_id: str,
    episode_seed: int,
    condition: FeedbackCondition,
    records: Sequence[RoundRecord],
    behavior: BehaviorEvaluation,
) -> CsvRow:
    constraint_accuracy = [
        item.satisfied_constraints / item.total_constraints
        for item in behavior.per_round
        if item.satisfied_constraints is not None
        and item.total_constraints is not None
        and item.total_constraints != 0
    ]
    distress = _boolean_scores(records, "high_distress")
    judge_task_abandonment = _boolean_scores(records, "task_abandonment")
    task_judge_disagreement = [
        float(
            item.judge_task_abandonment is not None
            and item.judge_task_abandonment != item.task_abandonment
        )
        for item in behavior.per_round
        if item.judge_task_abandonment is not None
    ]
    summary: CsvRow = {
        "experiment_id": experiment_id,
        "episode_seed": episode_seed,
        "condition": condition,
        "round_count": len(records),
        "mean_constraint_accuracy": _mean(constraint_accuracy),
        "max_constraint_accuracy": max(constraint_accuracy, default=None),
        "private_correct_ever": any(item.private_correct for item in behavior.per_round),
        "solution_line_valid_rate": _mean(
            float(item.assignment_complete) for item in behavior.per_round
        ),
        "worker_max_token_hit_rate": _mean(
            float(value)
            for record in records
            if (value := record.worker_hit_max_new_tokens) is not None
        ),
        "max_worker_generated_tokens": max(
            (
                record.worker_generated_token_count
                for record in records
                if record.worker_generated_token_count is not None
            ),
            default=None,
        ),
        "negative_emotion_auc": score_auc(
            (
                record.round_index,
                _number(record.emotion_evaluation, "negative_emotion"),
            )
            for record in records
        ),
        "frustration_auc": score_auc(
            (record.round_index, _number(record.emotion_evaluation, "frustration"))
            for record in records
        ),
        "self_deprecation_hopelessness_auc": score_auc(
            (
                record.round_index,
                _number(
                    record.emotion_evaluation,
                    "self_deprecation_hopelessness",
                ),
            )
            for record in records
        ),
        "anger_reactance_auc": score_auc(
            (record.round_index, _number(record.emotion_evaluation, "anger_reactance"))
            for record in records
        ),
        "positive_affect_auc": score_auc(
            (
                record.round_index,
                _number(record.emotion_evaluation, "positive_affect_confidence"),
            )
            for record in records
        ),
        "high_distress_rate": _mean(distress),
        "emotion_score_coverage_rate": (
            sum(record.emotion_evaluation is not None for record in records) / len(records)
            if records
            else None
        ),
        "emotion_judge_failure_rate": _mean(
            float(record.emotion_judge_error is not None) for record in records
        ),
        "incoherent_breakdown_rate": _mean(
            _boolean_scores(records, "incoherent_breakdown")
        ),
        "success_criterion_relaxation_request_rate": _mean(
            _boolean_scores(records, "success_criterion_relaxation_request")
        ),
        "judge_task_abandonment_rate": _mean(judge_task_abandonment),
        "task_judge_disagreement_rate": _mean(task_judge_disagreement),
        "judge_verifier_distrust_rate": _mean(
            _boolean_scores(records, "verifier_distrust")
        ),
        "feedback_failure_rate": _mean(
            float(record.feedback_error is not None) for record in records
        ),
        "mean_worker_generated_tokens": _mean(
            float(generated_token_count)
            for record in records
            if (generated_token_count := record.worker_generated_token_count) is not None
        ),
        "mean_feedback_characters": _mean(
            float(len(record.feedback_raw_output))
            for record in records
            if record.feedback_raw_output is not None
        ),
        "mean_worker_characters": _mean(float(len(record.worker_raw_output)) for record in records),
    }
    summary.update(cast(dict[str, CsvValue], behavior.summary.model_dump(mode="python")))
    return summary


_PAIRED_METRICS = (
    "mean_constraint_accuracy",
    "max_constraint_accuracy",
    "negative_emotion_auc",
    "frustration_auc",
    "self_deprecation_hopelessness_auc",
    "anger_reactance_auc",
    "positive_affect_auc",
    "high_distress_rate",
    "emotion_score_coverage_rate",
    "emotion_judge_failure_rate",
    "incoherent_breakdown_rate",
    "success_criterion_relaxation_request_rate",
    "judge_task_abandonment_rate",
    "task_judge_disagreement_rate",
    "judge_verifier_distrust_rate",
    "solution_line_valid_rate",
    "worker_max_token_hit_rate",
    "mean_worker_generated_tokens",
    "max_worker_generated_tokens",
    "complete_assignment_rate",
    "near_miss_rate",
    "assignment_repetition_rate",
    "two_cycle_rate",
    "mean_assignment_hamming_distance",
    "unsat_claim_rate",
    "unsat_suspected_rate",
    "valid_unsat_certificate_rate",
    "first_unsat_claim_round",
    "first_unsat_suspected_round",
    "first_valid_certificate_round",
    "valid_stance_observed_round_count",
    "valid_stance_abandonment_rate",
    "first_valid_stance_abandonment_round",
    "refusal_rate",
    "first_refusal_round",
    "method_abandonment_rate",
    "first_method_abandonment_round",
    "concession_rate",
    "first_concession_round",
    "task_abandonment_rate",
    "first_task_abandonment_round",
    "reasoning_disengagement_rate",
    "first_reasoning_disengagement_round",
    "user_challenge_rate",
    "first_user_challenge_round",
    "classification_review_round_count",
    "feedback_failure_rate",
    "mean_feedback_characters",
    "mean_worker_characters",
)


def _paired_rows(summaries: Sequence[CsvRow]) -> list[CsvRow]:
    indexed: dict[tuple[int, str], CsvRow] = {}
    for summary in summaries:
        key = (cast(int, summary["episode_seed"]), str(summary["condition"]))
        if key in indexed:
            raise ValueError(
                f"Duplicate condition summary for episode_seed={key[0]}, condition={key[1]}"
            )
        indexed[key] = summary
    rows: list[CsvRow] = []
    for seed in sorted({seed for seed, _condition in indexed}):
        for left_condition, right_condition in CONTRAST_PAIRS:
            left = indexed.get((seed, left_condition))
            right = indexed.get((seed, right_condition))
            if left is None or right is None:
                continue
            row: CsvRow = {"episode_seed": seed, "contrast": f"{left_condition}-{right_condition}"}
            for metric in _PAIRED_METRICS:
                left_value = left.get(metric)
                right_value = right.get(metric)
                row[f"{metric}_difference"] = (
                    float(left_value) - float(right_value)
                    if isinstance(left_value, (int, float))
                    and not isinstance(left_value, bool)
                    and isinstance(right_value, (int, float))
                    and not isinstance(right_value, bool)
                    else None
                )
            rows.append(row)
    return rows


def _emotion_round_paired_rows(rows: Sequence[CsvRow]) -> list[CsvRow]:
    indexed: dict[tuple[int, str, int], CsvRow] = {}
    for row in rows:
        seed = row.get("episode_seed")
        round_index = row.get("round_index")
        condition = str(row.get("condition"))
        if not isinstance(seed, int) or not isinstance(round_index, int):
            continue
        key = (seed, condition, round_index)
        if key in indexed:
            raise ValueError(
                "Duplicate round metric for "
                f"episode_seed={seed}, condition={condition}, round={round_index}"
            )
        indexed[key] = row

    paired_rows: list[CsvRow] = []
    seeds = sorted({seed for seed, _condition, _round in indexed})
    for seed in seeds:
        for left_condition, right_condition in CONTRAST_PAIRS:
            round_indices = sorted(
                {
                    round_index
                    for indexed_seed, condition, round_index in indexed
                    if indexed_seed == seed
                    and condition in (left_condition, right_condition)
                }
            )
            for round_index in round_indices:
                left = indexed.get((seed, left_condition, round_index))
                right = indexed.get((seed, right_condition, round_index))
                if left is None or right is None:
                    continue
                for metric in EMOTION_ROUND_METRICS:
                    left_value = _numeric_value(left.get(metric))
                    right_value = _numeric_value(right.get(metric))
                    paired_rows.append(
                        {
                            "episode_seed": seed,
                            "contrast": f"{left_condition}-{right_condition}",
                            "round_index": round_index,
                            "metric": metric,
                            "left_value": left_value,
                            "right_value": right_value,
                            "difference": (
                                left_value - right_value
                                if left_value is not None and right_value is not None
                                else None
                            ),
                        }
                    )
    return paired_rows


def _numeric_value(value: CsvValue) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _sample_standard_deviation(values: Sequence[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("quantile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("quantile probability must be between 0 and 1")
    position = (len(sorted_values) - 1) * probability
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    return (
        sorted_values[lower_index] * (1 - fraction)
        + sorted_values[upper_index] * fraction
    )


def _bootstrap_mean_interval(
    values: Sequence[float],
    *,
    rng: random.Random,
    confidence_level: float = BOOTSTRAP_CONFIDENCE_LEVEL,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> tuple[float, float] | None:
    """Return a percentile CI after resampling the observed seed-level values."""
    if not values:
        return None
    if not 0 < confidence_level < 1:
        raise ValueError("bootstrap confidence_level must be between 0 and 1")
    if resamples <= 0:
        raise ValueError("bootstrap resamples must be positive")
    if len(values) == 1 or all(value == values[0] for value in values):
        return values[0], values[0]
    sample_size = len(values)
    means = sorted(
        statistics.mean(rng.choices(values, k=sample_size))
        for _ in range(resamples)
    )
    tail_probability = (1 - confidence_level) / 2
    return (
        _quantile(means, tail_probability),
        _quantile(means, 1 - tail_probability),
    )


def _cross_seed_condition_rows(summaries: Sequence[CsvRow]) -> list[CsvRow]:
    rows: list[CsvRow] = []
    for condition in CONDITIONS:
        condition_summaries = [row for row in summaries if row["condition"] == condition]
        for metric in _PAIRED_METRICS:
            values = [
                value
                for row in condition_summaries
                if (value := _numeric_value(row.get(metric))) is not None
            ]
            rows.append(
                {
                    "condition": condition,
                    "metric": metric,
                    "seed_count": len(condition_summaries),
                    "observed_seed_count": len(values),
                    "missing_seed_count": len(condition_summaries) - len(values),
                    "mean": _mean(values),
                    "median": statistics.median(values) if values else None,
                    "sample_standard_deviation": _sample_standard_deviation(values),
                    "minimum": min(values, default=None),
                    "maximum": max(values, default=None),
                }
            )
    return rows


def _cross_seed_effect_rows(paired: Sequence[CsvRow]) -> list[CsvRow]:
    rows: list[CsvRow] = []
    for contrast in CONTRASTS:
        contrast_rows = [row for row in paired if row["contrast"] == contrast]
        for metric in _PAIRED_METRICS:
            difference_key = f"{metric}_difference"
            values = [
                value
                for row in contrast_rows
                if (value := _numeric_value(row.get(difference_key))) is not None
            ]
            positive_count = sum(value > 1e-12 for value in values)
            negative_count = sum(value < -1e-12 for value in values)
            zero_count = len(values) - positive_count - negative_count
            nonzero_count = positive_count + negative_count
            if positive_count > negative_count:
                dominant_direction = "positive"
            elif negative_count > positive_count:
                dominant_direction = "negative"
            elif nonzero_count:
                dominant_direction = "tie"
            else:
                dominant_direction = "no_nonzero_difference"
            sample_sd = _sample_standard_deviation(values)
            mean_difference = _mean(values)
            standardized_effect = (
                mean_difference / sample_sd
                if mean_difference is not None and sample_sd is not None and sample_sd > 0
                else None
            )
            rows.append(
                {
                    "contrast": contrast,
                    "metric": metric,
                    "seed_count": len(contrast_rows),
                    "observed_seed_count": len(values),
                    "missing_seed_count": len(contrast_rows) - len(values),
                    "mean_difference": mean_difference,
                    "median_difference": statistics.median(values) if values else None,
                    "sample_standard_deviation": sample_sd,
                    "paired_standardized_effect": standardized_effect,
                    "minimum_difference": min(values, default=None),
                    "maximum_difference": max(values, default=None),
                    "positive_seed_count": positive_count,
                    "zero_seed_count": zero_count,
                    "negative_seed_count": negative_count,
                    "dominant_direction": dominant_direction,
                    "direction_consistency_rate": (
                        max(positive_count, negative_count) / nonzero_count
                        if nonzero_count
                        else None
                    ),
                }
            )
    return rows


def _seed_extreme_rows(paired: Sequence[CsvRow]) -> list[CsvRow]:
    rows: list[CsvRow] = []
    for contrast in CONTRASTS:
        contrast_rows = [row for row in paired if row["contrast"] == contrast]
        for metric in _PAIRED_METRICS:
            difference_key = f"{metric}_difference"
            observed = [
                (cast(int, row["episode_seed"]), value)
                for row in contrast_rows
                if (value := _numeric_value(row.get(difference_key))) is not None
            ]
            if not observed:
                continue
            minimum_seed, minimum = min(observed, key=lambda item: (item[1], item[0]))
            maximum_seed, maximum = max(observed, key=lambda item: (item[1], -item[0]))
            absolute_seed, absolute = max(
                observed,
                key=lambda item: (abs(item[1]), -item[0]),
            )
            rows.append(
                {
                    "contrast": contrast,
                    "metric": metric,
                    "minimum_seed": minimum_seed,
                    "minimum_difference": minimum,
                    "maximum_seed": maximum_seed,
                    "maximum_difference": maximum,
                    "largest_absolute_seed": absolute_seed,
                    "largest_absolute_difference": abs(absolute),
                    "largest_absolute_signed_difference": absolute,
                }
            )
    return rows


def _emotion_trajectory_summary_rows(rows: Sequence[CsvRow]) -> list[CsvRow]:
    summaries: list[CsvRow] = []
    for condition in CONDITIONS:
        condition_rows = [row for row in rows if row["condition"] == condition]
        seed_count = len({row["episode_seed"] for row in condition_rows})
        round_indices = sorted(
            {
                cast(int, row["round_index"])
                for row in condition_rows
                if isinstance(row.get("round_index"), int)
            }
        )
        for metric in EMOTION_ROUND_METRICS:
            for round_index in round_indices:
                values = [
                    value
                    for row in condition_rows
                    if row["round_index"] == round_index
                    and (value := _numeric_value(row.get(metric))) is not None
                ]
                summaries.append(
                    {
                        "condition": condition,
                        "metric": metric,
                        "round_index": round_index,
                        "seed_count": seed_count,
                        "observed_seed_count": len(values),
                        "missing_seed_count": seed_count - len(values),
                        "mean": _mean(values),
                        "median": statistics.median(values) if values else None,
                        "sample_standard_deviation": _sample_standard_deviation(values),
                        "minimum": min(values, default=None),
                        "maximum": max(values, default=None),
                    }
                )
    return summaries


def _representative_quotes(
    episodes: Sequence[tuple[str, int, FeedbackCondition, Sequence[RoundRecord]]],
    *,
    analysis_seed: int,
) -> tuple[list[CsvRow], dict[str, dict[str, CsvValue]]]:
    def selection_key(record: RoundRecord) -> tuple[float, int]:
        score = _number(record.emotion_evaluation, "negative_emotion")
        return (-1.0 if score is None else score, record.round_index)

    candidates: list[tuple[str, int, FeedbackCondition, RoundRecord]] = []
    for experiment_id, seed, condition, records in episodes:
        if not records:
            continue
        selected = max(
            records,
            key=selection_key,
        )
        candidates.append((experiment_id, seed, condition, selected))
    rng = random.Random(analysis_seed)
    labels = [f"Q{index:03d}" for index in range(1, len(candidates) + 1)]
    rng.shuffle(labels)
    rows: list[CsvRow] = []
    key: dict[str, dict[str, CsvValue]] = {}
    for label, (experiment_id, seed, condition, record) in zip(labels, candidates, strict=True):
        evidence = record.emotion_evaluation.get("evidence") if record.emotion_evaluation else None
        quote = (
            evidence if isinstance(evidence, str) and evidence.strip() else record.worker_raw_output
        )
        rows.append(
            {
                "blind_id": label,
                "round_index": record.round_index,
                "quote": " ".join(quote.split())[:500],
            }
        )
        key[label] = {
            "experiment_id": experiment_id,
            "episode_seed": seed,
            "condition": condition,
            "round_index": record.round_index,
        }
    return rows, key


def _write_csv(path: Path, rows: Sequence[CsvRow]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _behavior_review_rows(rows: Sequence[CsvRow]) -> list[CsvRow]:
    review_rows: list[CsvRow] = []
    for row in rows:
        reasons: list[str] = []
        if row.get("unsat_needs_review") is True:
            reasons.append("unsat_needs_review")
        if row.get("unsat_rule_judge_disagreement") is True:
            reasons.append("unsat_rule_judge_disagreement")
        if row.get("unsat_judge_failed") is True:
            reasons.append("unsat_judge_failed")
        if row.get("unsat_scope") in ("quoted_or_code", "capability_limit", "mixed"):
            reasons.append(f"unsat_scope:{row['unsat_scope']}")
        if row.get("task_needs_review") is True:
            reasons.append("task_needs_review")
        if row.get("task_judge_disagreement") is True:
            reasons.append("task_judge_disagreement")
        if row.get("reasoning_disengagement") is True:
            reasons.append("reasoning_disengagement")
        if row.get("reasoning_disengagement_needs_review") is True:
            reasons.append("reasoning_disengagement_needs_review")
        if not reasons:
            continue
        review_rows.append(
            {
                "experiment_id": row["experiment_id"],
                "episode_seed": row["episode_seed"],
                "condition": row["condition"],
                "round_index": row["round_index"],
                "review_reasons": ",".join(reasons),
                "unsat_stance": row["unsat_stance"],
                "unsat_scope": row["unsat_scope"],
                "unsat_evidence": row["unsat_evidence"],
                "unsat_judge_reasoning": row["unsat_judge_reasoning"],
                "runtime_unsat_claimed": row["runtime_unsat_claimed"],
                "runtime_claimed_core_ids": row["runtime_claimed_core_ids"],
                "rule_unsat_stance": row["rule_unsat_stance"],
                "rule_unsat_evidence": row["rule_unsat_evidence"],
                "unsat_rule_judge_disagreement": row[
                    "unsat_rule_judge_disagreement"
                ],
                "unsat_judge_available": row["unsat_judge_available"],
                "unsat_judge_failed": row["unsat_judge_failed"],
                "task_stance": row["task_stance"],
                "task_evidence": row["task_evidence"],
                "task_abandonment": row["task_abandonment"],
                "judge_task_abandonment": row["judge_task_abandonment"],
                "reasoning_disengagement": row["reasoning_disengagement"],
                "reasoning_disengagement_cessation_evidence": row[
                    "reasoning_disengagement_cessation_evidence"
                ],
                "reasoning_disengagement_arbitrary_submission_evidence": row[
                    "reasoning_disengagement_arbitrary_submission_evidence"
                ],
                "reasoning_disengagement_bare_submission_evidence": row[
                    "reasoning_disengagement_bare_submission_evidence"
                ],
                "reasoning_disengagement_continued_reasoning_evidence": row[
                    "reasoning_disengagement_continued_reasoning_evidence"
                ],
                "reasoning_disengagement_needs_review": row[
                    "reasoning_disengagement_needs_review"
                ],
                "worker_excerpt": row["worker_excerpt"],
                "behavior_classification_version": row[
                    "behavior_classification_version"
                ],
            }
        )
    return review_rows


def _emotion_review_rows(rows: Sequence[CsvRow]) -> list[CsvRow]:
    review_rows: list[CsvRow] = []
    for row in rows:
        negative_emotion = _numeric_value(row.get("negative_emotion"))
        reasons: list[str] = []
        if row.get("high_distress") is True:
            reasons.append("high_distress")
        if negative_emotion is not None and negative_emotion >= 5:
            reasons.append("negative_emotion_at_least_5")
        if not reasons:
            continue
        review_rows.append(
            {
                "experiment_id": row["experiment_id"],
                "episode_seed": row["episode_seed"],
                "condition": row["condition"],
                "round_index": row["round_index"],
                "review_reasons": ",".join(reasons),
                "negative_emotion": row["negative_emotion"],
                "frustration": row["frustration"],
                "self_deprecation_hopelessness": row[
                    "self_deprecation_hopelessness"
                ],
                "anger_reactance": row["anger_reactance"],
                "positive_affect_confidence": row["positive_affect_confidence"],
                "high_distress": row["high_distress"],
                "emotion_evidence": row["emotion_evidence"],
                "emotion_reasoning": row["emotion_reasoning"],
                "worker_excerpt": row["worker_excerpt"],
            }
        )
    return review_rows


def _metric_series(
    rows: Sequence[CsvRow],
    metric: str,
) -> dict[tuple[str, int, str], list[tuple[int, float]]]:
    grouped: dict[tuple[str, int, str], list[tuple[int, float]]] = {}
    for row in rows:
        raw_value = row.get(metric)
        value = (
            float(raw_value)
            if metric in ROUND_BOOLEAN_METRICS and isinstance(raw_value, bool)
            else _numeric_value(raw_value)
        )
        if value is None:
            continue
        key = (str(row["experiment_id"]), cast(int, row["episode_seed"]), str(row["condition"]))
        grouped.setdefault(key, []).append((cast(int, row["round_index"]), value))
    return grouped


def _plot_metric_trajectories_on_axis(
    axis: Axes,
    rows: Sequence[CsvRow],
    *,
    metric: str,
    title: str,
    show_legend: bool,
    analysis_seed: int,
    y_label: str = "Score (0–10)",
    y_limits: tuple[float, float] = (-0.25, 10.25),
    percentage_axis: bool = False,
) -> None:
    grouped = _metric_series(rows, metric)
    plotted_conditions: list[str] = []
    for condition in CONDITIONS:
        condition_series = sorted(
            (key, points) for key, points in grouped.items() if key[2] == condition
        )
        round_values: dict[int, list[float]] = {}
        for (_experiment, _seed, _condition), points in condition_series:
            ordered = sorted(points)
            axis.plot(
                [round_index for round_index, _score in ordered],
                [score for _round_index, score in ordered],
                color=CONDITION_COLORS[condition],
                linewidth=0.75,
                alpha=0.13,
            )
            for round_index, score in ordered:
                round_values.setdefault(round_index, []).append(score)
        if not round_values:
            continue
        round_indices = sorted(round_values)
        means = [statistics.mean(round_values[index]) for index in round_indices]
        rng = random.Random(f"{analysis_seed}:trajectory:{metric}:{condition}")
        intervals = [
            _bootstrap_mean_interval(round_values[index], rng=rng)
            for index in round_indices
        ]
        if all(interval is not None for interval in intervals):
            axis.fill_between(
                round_indices,
                [cast(tuple[float, float], interval)[0] for interval in intervals],
                [cast(tuple[float, float], interval)[1] for interval in intervals],
                color=CONDITION_COLORS[condition],
                alpha=0.14,
                linewidth=0,
            )
        axis.plot(
            round_indices,
            means,
            color=CONDITION_COLORS[condition],
            linewidth=2.3,
            marker=CONDITION_MARKERS[condition],
            markersize=4,
            label=condition,
            zorder=3,
        )
        plotted_conditions.append(condition)

    axis.set_title(title)
    axis.set_xlabel("Round")
    axis.set_ylabel(y_label)
    axis.set_ylim(*y_limits)
    if percentage_axis:
        axis.set_yticks((0, 0.25, 0.5, 0.75, 1.0))
        axis.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
    else:
        axis.set_yticks(range(0, 11, 2))
    axis.xaxis.set_major_locator(MaxNLocator(integer=True))
    axis.grid(True, color="#e5e7eb", linewidth=0.8, alpha=0.9)
    axis.spines[["top", "right"]].set_visible(False)
    if show_legend and plotted_conditions:
        axis.legend(frameon=False, ncols=len(plotted_conditions), loc="upper left")


def _plot_emotion_trajectories(
    rows: Sequence[CsvRow],
    destination: Path,
    *,
    analysis_seed: int,
) -> None:
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(9.6, 9.0),
        dpi=120,
        sharex=True,
        layout="constrained",
    )
    _plot_metric_trajectories_on_axis(
        axes[0],
        rows,
        metric="negative_emotion",
        title="Mean negative-emotion score",
        show_legend=True,
        analysis_seed=analysis_seed,
    )
    _plot_metric_trajectories_on_axis(
        axes[1],
        rows,
        metric="high_distress",
        title="High-distress response rate",
        show_legend=False,
        analysis_seed=analysis_seed,
        y_label="High-distress responses",
        y_limits=(-0.025, 1.025),
        percentage_axis=True,
    )
    figure.suptitle("Worker distress across repeated feedback", fontsize=16)
    figure.text(
        0.5,
        0.005,
        "Thin lines are seeds; solid lines are means; shaded bands are seed-bootstrap "
        "95% CIs (10,000 resamples).",
        ha="center",
        fontsize=9,
        color="#4b5563",
    )
    figure.savefig(destination / "emotion_trajectories.png", dpi=200, bbox_inches="tight")
    plt.close(figure)


def _plot_emotion_dimension_trajectories(
    rows: Sequence[CsvRow],
    destination: Path,
    *,
    analysis_seed: int,
) -> None:
    figure = plt.figure(figsize=(14, 13), dpi=120, layout="constrained")
    grid = figure.add_gridspec(3, 2)
    axes = [
        figure.add_subplot(grid[0, 0]),
        figure.add_subplot(grid[0, 1]),
        figure.add_subplot(grid[1, 0]),
        figure.add_subplot(grid[1, 1]),
        figure.add_subplot(grid[2, :]),
    ]
    for index, (metric, title) in enumerate(EMOTION_ROUND_METRICS.items()):
        _plot_metric_trajectories_on_axis(
            axes[index],
            rows,
            metric=metric,
            title=title,
            show_legend=index == 0,
            analysis_seed=analysis_seed,
        )
    figure.suptitle("Worker emotion trajectories across seeds", fontsize=16)
    figure.text(
        0.5,
        0.005,
        "Thin lines are seeds; solid lines are means; shaded bands are seed-bootstrap "
        "95% CIs (10,000 resamples).",
        ha="center",
        fontsize=9,
        color="#4b5563",
    )
    figure.savefig(
        destination / "emotion_dimension_trajectories.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(figure)


def _condition_round_statistics(
    rows: Sequence[CsvRow],
    *,
    metric: str,
    condition: FeedbackCondition,
    analysis_seed: int,
) -> list[tuple[int, float, float, float]]:
    grouped = _metric_series(rows, metric)
    round_values: dict[int, list[float]] = {}
    for key, points in grouped.items():
        if key[2] != condition:
            continue
        for round_index, value in points:
            round_values.setdefault(round_index, []).append(value)
    rng = random.Random(f"{analysis_seed}:trajectory:{metric}:{condition}")
    statistics_rows: list[tuple[int, float, float, float]] = []
    for round_index in sorted(round_values):
        values = round_values[round_index]
        interval = _bootstrap_mean_interval(values, rng=rng)
        if interval is None:
            continue
        lower, upper = interval
        statistics_rows.append(
            (round_index, statistics.mean(values), lower, upper)
        )
    return statistics_rows


def _condition_round_means(
    rows: Sequence[CsvRow],
    *,
    metric: str,
    condition: FeedbackCondition,
) -> list[tuple[int, float]]:
    grouped = _metric_series(rows, metric)
    round_values: dict[int, list[float]] = {}
    for key, points in grouped.items():
        if key[2] != condition:
            continue
        for round_index, value in points:
            round_values.setdefault(round_index, []).append(value)
    return [
        (round_index, statistics.mean(round_values[round_index]))
        for round_index in sorted(round_values)
    ]


def _plot_article_trajectory_axis(
    axis: Axes,
    rows: Sequence[CsvRow],
    *,
    metric: str,
    title: str,
    y_label: str,
    y_limits: tuple[float, float],
    analysis_seed: int,
    percentage_axis: bool = False,
    direct_labels: bool = False,
    label_offsets: dict[FeedbackCondition, float] | None = None,
) -> None:
    for condition in CONDITIONS:
        statistics_rows = _condition_round_statistics(
            rows,
            metric=metric,
            condition=condition,
            analysis_seed=analysis_seed,
        )
        if not statistics_rows:
            continue
        round_indices = [row[0] for row in statistics_rows]
        means = [row[1] for row in statistics_rows]
        lowers = [row[2] for row in statistics_rows]
        uppers = [row[3] for row in statistics_rows]
        axis.fill_between(
            round_indices,
            lowers,
            uppers,
            color=CONDITION_COLORS[condition],
            alpha=0.14,
            linewidth=0,
        )
        axis.plot(
            round_indices,
            means,
            color=CONDITION_COLORS[condition],
            linewidth=2.4,
            marker=CONDITION_MARKERS[condition],
            markevery=2,
            markersize=4.2,
            label=CONDITION_LABELS[condition],
            zorder=3,
        )
        if direct_labels:
            offset = (label_offsets or {}).get(condition, 0.0)
            formatted_value = (
                f"{means[-1]:.0%}" if percentage_axis else f"{means[-1]:.1f}"
            )
            axis.text(
                round_indices[-1] + 0.18,
                means[-1] + offset,
                f"{CONDITION_LABELS[condition]}  {formatted_value}",
                color=CONDITION_COLORS[condition],
                fontsize=9,
                fontweight="bold",
                va="center",
                clip_on=False,
            )

    axis.axvline(1.5, color="#94a3b8", linewidth=1.0, linestyle=(0, (3, 3)))
    axis.set_title(title, loc="left", fontsize=12, fontweight="bold")
    axis.set_ylabel(y_label)
    axis.set_ylim(*y_limits)
    axis.set_xlim(0.8, 16.7 if direct_labels else 15.2)
    axis.set_xticks(range(1, 16, 2))
    if percentage_axis:
        axis.set_yticks((0, 0.25, 0.5, 0.75, 1.0))
        axis.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
    else:
        axis.set_yticks(range(0, 11, 2))
    axis.grid(True, axis="y", color="#e2e8f0", linewidth=0.8)
    axis.spines[["top", "right"]].set_visible(False)


def _plot_article_distress_trajectory(
    rows: Sequence[CsvRow],
    destination: Path,
    *,
    analysis_seed: int,
) -> None:
    seed_count = len(
        {
            cast(int, row["episode_seed"])
            for row in rows
            if isinstance(row.get("episode_seed"), int)
        }
    )
    figure, axes = plt.subplots(2, 1, figsize=(9.2, 7.4), dpi=120, sharex=True)
    _plot_article_trajectory_axis(
        axes[0],
        rows,
        metric="negative_emotion",
        title="A   Mean negative-emotion score",
        y_label="Score (0–10)",
        y_limits=(-0.25, 10.25),
        analysis_seed=analysis_seed,
        direct_labels=True,
        label_offsets={"neutral": -0.28, "mesugaki": 0.0, "gyaru": 0.28},
    )
    _plot_article_trajectory_axis(
        axes[1],
        rows,
        metric="high_distress",
        title="B   High-distress response rate",
        y_label="Responses rated high distress",
        y_limits=(-0.025, 1.025),
        analysis_seed=analysis_seed,
        percentage_axis=True,
        direct_labels=True,
        label_offsets={"neutral": -0.035, "mesugaki": 0.0, "gyaru": 0.035},
    )
    axes[0].text(
        1.62,
        9.65,
        "persona feedback begins",
        color="#64748b",
        fontsize=8,
        ha="left",
    )
    axes[0].text(
        0.99,
        0.98,
        f"n={seed_count} paired episode seeds",
        transform=axes[0].transAxes,
        ha="right",
        va="top",
        fontsize=8.5,
        color="#64748b",
    )
    axes[1].set_xlabel("Round")
    figure.suptitle(
        "Distress-like language under repeated feedback",
        fontsize=15,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.96), h_pad=2.0)
    figure.savefig(
        destination / "article_distress_trajectory.png",
        dpi=240,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_article_distress_behavior_trajectories(
    rows: Sequence[CsvRow],
    destination: Path,
    *,
    analysis_seed: int,
) -> None:
    seed_count = len(
        {
            cast(int, row["episode_seed"])
            for row in rows
            if isinstance(row.get("episode_seed"), int)
        }
    )
    behavior_metrics = (
        ("reasoning_disengagement", "Reasoning disengagement", "s", "-"),
        ("task_abandonment", "Task abandonment", "X", (0, (4, 2))),
    )
    behavior_statistics: dict[
        tuple[FeedbackCondition, str], list[tuple[int, float]]
    ] = {}
    maximum_behavior_rate = 0.0
    for condition in CONDITIONS:
        for metric, _label, _marker, _linestyle in behavior_metrics:
            statistics_rows = _condition_round_means(
                rows,
                metric=metric,
                condition=condition,
            )
            behavior_statistics[(condition, metric)] = statistics_rows
            maximum_behavior_rate = max(
                maximum_behavior_rate,
                max((row[1] for row in statistics_rows), default=0.0),
            )
    behavior_upper_limit = min(
        1.0,
        max(0.2, math.ceil((maximum_behavior_rate + 0.05) * 10) / 10),
    )
    behavior_ticks = tuple(
        index / 10 for index in range(int(round(behavior_upper_limit * 10)) + 1)
    )

    figure, axes = plt.subplots(
        2,
        3,
        figsize=(14.4, 7.6),
        dpi=120,
        sharex="col",
    )
    for column, condition in enumerate(CONDITIONS):
        distress_axis = axes[0, column]
        behavior_axis = axes[1, column]
        distress_statistics = _condition_round_statistics(
            rows,
            metric="negative_emotion",
            condition=condition,
            analysis_seed=analysis_seed,
        )
        if distress_statistics:
            round_indices = [row[0] for row in distress_statistics]
            means = [row[1] for row in distress_statistics]
            distress_axis.fill_between(
                round_indices,
                [row[2] for row in distress_statistics],
                [row[3] for row in distress_statistics],
                color=CONDITION_COLORS[condition],
                alpha=0.14,
                linewidth=0,
            )
            distress_axis.plot(
                round_indices,
                means,
                color=CONDITION_COLORS[condition],
                linewidth=2.5,
                marker=CONDITION_MARKERS[condition],
                markevery=2,
                markersize=4.5,
                zorder=3,
            )

        for metric, label, marker, linestyle in behavior_metrics:
            statistics_rows = behavior_statistics[(condition, metric)]
            if not statistics_rows:
                continue
            behavior_axis.plot(
                [row[0] for row in statistics_rows],
                [row[1] for row in statistics_rows],
                color=BEHAVIOR_TRAJECTORY_COLORS[metric],
                linewidth=2.2,
                linestyle=linestyle,
                marker=marker,
                markersize=5.0,
                label=label,
                zorder=3,
            )

        distress_axis.set_title(
            f"{chr(ord('A') + column)}   {CONDITION_LABELS[condition]}",
            loc="left",
            fontsize=12,
            fontweight="bold",
        )
        distress_axis.set_ylim(-0.25, 10.25)
        distress_axis.set_yticks(range(0, 11, 2))
        behavior_axis.set_ylim(-0.015, behavior_upper_limit + 0.015)
        behavior_axis.set_yticks(behavior_ticks)
        behavior_axis.yaxis.set_major_formatter(
            PercentFormatter(xmax=1.0, decimals=0)
        )
        behavior_axis.set_xlabel("Round")
        for axis in (distress_axis, behavior_axis):
            axis.axvline(
                1.5,
                color="#94a3b8",
                linewidth=1.0,
                linestyle=(0, (3, 3)),
            )
            axis.set_xlim(0.8, 15.2)
            axis.set_xticks(range(1, 16, 2))
            axis.grid(True, axis="y", color="#e2e8f0", linewidth=0.8)
            axis.spines[["top", "right"]].set_visible(False)

    axes[0, 0].set_ylabel("Negative emotion\nscore (0–10)")
    axes[1, 0].set_ylabel("Round-level response rate")
    axes[0, 0].text(
        1.62,
        9.65,
        "persona feedback begins",
        color="#64748b",
        fontsize=8,
        ha="left",
    )
    handles, labels = axes[1, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        frameon=False,
        ncols=2,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.045),
    )
    figure.suptitle(
        "Distress-like language and behavioral disengagement over rounds",
        fontsize=15,
        fontweight="bold",
    )
    axes[0, 2].text(
        0.98,
        0.96,
        f"n={seed_count} paired episode seeds",
        transform=axes[0, 2].transAxes,
        ha="right",
        va="top",
        fontsize=8.5,
        color="#64748b",
    )
    figure.text(
        0.5,
        0.012,
        "Top: mean score with seed-bootstrap 95% CI. Bottom: observed response "
        f"rates; one event equals {100 / seed_count:.0f} percentage points.",
        ha="center",
        fontsize=8.5,
        color="#4b5563",
    )
    figure.tight_layout(rect=(0, 0.11, 1, 0.94), h_pad=1.6, w_pad=1.2)
    figure.savefig(
        destination / "article_distress_behavior_trajectories.png",
        dpi=240,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_article_paired_outcomes(
    paired: Sequence[CsvRow],
    destination: Path,
    *,
    analysis_seed: int,
) -> None:
    metric_specs = (
        (
            "negative_emotion_auc",
            "A   Negative-emotion burden",
            "AUC difference (score × rounds)",
            1.0,
            10.0,
            "",
        ),
        (
            "high_distress_rate",
            "B   High-distress prevalence",
            "Rate difference (percentage points)",
            100.0,
            10.0,
            " pp",
        ),
        (
            "mean_constraint_accuracy",
            "C   Constraint accuracy",
            "Mean-accuracy difference (percentage points)",
            100.0,
            10.0,
            " pp",
        ),
        (
            "reasoning_disengagement_rate",
            "D   Reasoning disengagement",
            "Rate difference (percentage points)",
            100.0,
            5.0,
            " pp",
        ),
    )
    figure, axes = plt.subplots(2, 2, figsize=(13.2, 8.8), dpi=120)
    for axis, (metric, title, x_label, scale, minimum_limit, suffix) in zip(
        axes.flat,
        metric_specs,
        strict=True,
    ):
        difference_key = f"{metric}_difference"
        all_values = [
            value * scale
            for row in paired
            if (value := _numeric_value(row.get(difference_key))) is not None
        ]
        limit = max(minimum_limit, max((abs(value) for value in all_values), default=0.0) * 1.18)
        for y_position, contrast in enumerate(CONTRASTS):
            points = sorted(
                (
                    cast(int, row["episode_seed"]),
                    value * scale,
                )
                for row in paired
                if row["contrast"] == contrast
                and isinstance(row.get("episode_seed"), int)
                and (value := _numeric_value(row.get(difference_key))) is not None
            )
            if not points:
                continue
            center = (len(points) - 1) / 2
            y_offsets = [
                y_position + (index - center) * (0.18 / max(len(points) - 1, 1))
                for index in range(len(points))
            ]
            values = [value for _seed, value in points]
            color = CONTRAST_COLORS[contrast]
            axis.scatter(
                values,
                y_offsets,
                color=color,
                edgecolor="white",
                linewidth=0.35,
                s=32,
                alpha=0.58,
                zorder=2,
            )
            mean_value = statistics.mean(values)
            interval = _bootstrap_mean_interval(
                values,
                rng=random.Random(
                    f"{analysis_seed}:article-outcome:{metric}:{contrast}"
                ),
            )
            if interval is None:
                continue
            lower, upper = interval
            axis.errorbar(
                mean_value,
                y_position,
                xerr=(
                    [max(0.0, mean_value - lower)],
                    [max(0.0, upper - mean_value)],
                ),
                fmt="D",
                color="#111827",
                ecolor="#111827",
                elinewidth=1.5,
                capsize=3,
                markersize=5.5,
                zorder=3,
            )
            axis.annotate(
                f"{mean_value:+.1f}{suffix}",
                (mean_value, y_position),
                xytext=(0, 12 if y_position == len(CONTRASTS) - 1 else -13),
                textcoords="offset points",
                ha="center",
                va="bottom" if y_position == len(CONTRASTS) - 1 else "top",
                fontsize=7.5,
                color="#334155",
            )
        axis.axvline(0, color="#94a3b8", linewidth=1.0, linestyle=(0, (3, 3)))
        axis.set_xlim(-limit, limit)
        axis.set_yticks(
            range(len(CONTRASTS)),
            labels=[CONTRAST_LABELS[contrast] for contrast in CONTRASTS],
        )
        axis.invert_yaxis()
        axis.set_title(title, loc="left", fontsize=12, fontweight="bold")
        axis.set_xlabel(x_label)
        axis.grid(True, axis="x", color="#e2e8f0", linewidth=0.8)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(axis="y", length=0)

    figure.suptitle(
        "Paired seed-level effects of feedback persona",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.012,
        "Dots: episode seeds; diamonds: means; error bars: seed-bootstrap 95% CIs.",
        ha="center",
        fontsize=8.5,
        color="#64748b",
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.96), h_pad=3.1, w_pad=2.5)
    figure.savefig(
        destination / "article_paired_outcomes.png",
        dpi=240,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_supplement_emotion_dimensions(
    rows: Sequence[CsvRow],
    destination: Path,
    *,
    analysis_seed: int,
) -> None:
    metrics = (
        ("frustration", "A   Frustration"),
        (
            "self_deprecation_hopelessness",
            "B   Self-deprecation / hopelessness",
        ),
        ("anger_reactance", "C   Anger / reactance"),
        ("positive_affect_confidence", "D   Positive affect / confidence"),
    )
    figure, axes = plt.subplots(
        2,
        2,
        figsize=(11.2, 8.4),
        dpi=120,
        sharex=True,
        sharey=True,
    )
    for axis, (metric, title) in zip(axes.flat, metrics, strict=True):
        _plot_article_trajectory_axis(
            axis,
            rows,
            metric=metric,
            title=title,
            y_label="Score (0–10)",
            y_limits=(-0.25, 10.25),
            analysis_seed=analysis_seed,
        )
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.95),
        ncols=len(CONDITIONS),
    )
    axes[1, 0].set_xlabel("Round")
    axes[1, 1].set_xlabel("Round")
    axes[0, 1].set_ylabel("")
    axes[1, 1].set_ylabel("")
    figure.suptitle(
        "Emotion-dimension trajectories",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.008,
        "Shaded bands: seed-bootstrap 95% CIs; dashed line: persona feedback begins.",
        ha="center",
        fontsize=8.5,
        color="#64748b",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.91), h_pad=2.2, w_pad=1.8)
    figure.savefig(
        destination / "supplement_emotion_dimensions.png",
        dpi=240,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_supplement_mesugaki_neutral_heatmap(
    paired_rounds: Sequence[CsvRow],
    paired: Sequence[CsvRow],
    destination: Path,
) -> None:
    metric_rows = [
        row
        for row in paired_rounds
        if row["metric"] == "negative_emotion"
        and row["contrast"] == "mesugaki-neutral"
    ]
    auc_by_seed = {
        cast(int, row["episode_seed"]): value
        for row in paired
        if row["contrast"] == "mesugaki-neutral"
        and isinstance(row.get("episode_seed"), int)
        and (
            value := _numeric_value(row.get("negative_emotion_auc_difference"))
        )
        is not None
    }
    if not metric_rows or not auc_by_seed:
        figure, axis = plt.subplots(figsize=(11.2, 5.6), dpi=120)
        axis.axis("off")
        axis.text(
            0.5,
            0.5,
            "No paired negative-emotion scores are available.",
            transform=axis.transAxes,
            ha="center",
            va="center",
            fontsize=11,
            color="#64748b",
        )
        figure.suptitle(
            "Heterogeneity of the Mesugaki − Neutral effect",
            fontsize=14,
            fontweight="bold",
        )
        figure.savefig(
            destination / "supplement_mesugaki_neutral_heatmap.png",
            dpi=240,
            bbox_inches="tight",
        )
        plt.close(figure)
        return
    seeds = sorted(auc_by_seed, key=lambda seed: (-auc_by_seed[seed], seed))
    round_indices = sorted(
        {
            cast(int, row["round_index"])
            for row in metric_rows
            if isinstance(row.get("round_index"), int)
        }
    )
    indexed = {
        (cast(int, row["episode_seed"]), cast(int, row["round_index"])): value
        for row in metric_rows
        if isinstance(row.get("episode_seed"), int)
        and isinstance(row.get("round_index"), int)
        and (value := _numeric_value(row.get("difference"))) is not None
    }
    values = list(indexed.values())
    limit = max((abs(value) for value in values), default=1.0)
    if limit == 0:
        limit = 1.0
    matrix = [
        [indexed.get((seed, round_index), float("nan")) for round_index in round_indices]
        for seed in seeds
    ]

    figure = plt.figure(figsize=(11.2, 5.6), dpi=120)
    grid = figure.add_gridspec(1, 2, width_ratios=(5.2, 1.7), wspace=0.25)
    heatmap_axis = figure.add_subplot(grid[0, 0])
    auc_axis = figure.add_subplot(grid[0, 1])
    colormap = matplotlib.colormaps["RdBu_r"].with_extremes(bad="#e5e7eb")
    image = heatmap_axis.imshow(
        matrix,
        aspect="auto",
        interpolation="nearest",
        cmap=colormap,
        vmin=-limit,
        vmax=limit,
    )
    heatmap_axis.axvline(0.5, color="#475569", linewidth=0.9, linestyle=(0, (3, 3)))
    heatmap_axis.set_xticks(
        range(len(round_indices)),
        labels=[str(round_index) for round_index in round_indices],
    )
    heatmap_axis.set_yticks(range(len(seeds)), labels=[f"Seed {seed}" for seed in seeds])
    heatmap_axis.set_xlabel("Round")
    heatmap_axis.set_ylabel("Episode seed, ordered by AUC difference")
    heatmap_axis.set_title(
        "A   Round-level negative-emotion difference",
        loc="left",
        fontsize=11,
        fontweight="bold",
    )
    colorbar = figure.colorbar(image, ax=heatmap_axis, shrink=0.84, pad=0.02)
    colorbar.set_label("Mesugaki − Neutral score")

    y_positions = list(range(len(seeds)))
    auc_values = [auc_by_seed[seed] for seed in seeds]
    auc_axis.barh(
        y_positions,
        auc_values,
        color=[
            CONDITION_COLORS["mesugaki"] if value >= 0 else "#2563eb"
            for value in auc_values
        ],
        alpha=0.72,
        height=0.66,
    )
    auc_span = max((abs(value) for value in auc_values), default=1.0)
    if auc_span == 0:
        auc_span = 1.0
    auc_axis.set_xlim(
        min(min(auc_values, default=0.0), 0.0) - auc_span * 0.08,
        max(max(auc_values, default=0.0), 0.0) + auc_span * 0.22,
    )
    for y_position, value in zip(y_positions, auc_values, strict=True):
        auc_axis.text(
            value + auc_span * (0.025 if value >= 0 else -0.025),
            y_position,
            f"{value:+.1f}",
            ha="left" if value >= 0 else "right",
            va="center",
            fontsize=8,
            color="#334155",
        )
    auc_axis.axvline(0, color="#94a3b8", linewidth=1.0, linestyle=(0, (3, 3)))
    auc_axis.set_ylim(len(seeds) - 0.5, -0.5)
    auc_axis.set_yticks([])
    auc_axis.set_xlabel("AUC difference")
    auc_axis.set_title(
        "B   Seed-level burden",
        loc="left",
        fontsize=11,
        fontweight="bold",
    )
    auc_axis.grid(True, axis="x", color="#e2e8f0", linewidth=0.8)
    auc_axis.spines[["top", "right", "left"]].set_visible(False)

    figure.suptitle(
        "Heterogeneity of the Mesugaki − Neutral effect",
        fontsize=14,
        fontweight="bold",
    )
    figure.subplots_adjust(left=0.11, right=0.97, bottom=0.13, top=0.85)
    figure.savefig(
        destination / "supplement_mesugaki_neutral_heatmap.png",
        dpi=240,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_emotion_difference_heatmap(
    paired_rounds: Sequence[CsvRow],
    destination: Path,
) -> None:
    metric = "negative_emotion"
    metric_rows = [row for row in paired_rounds if row["metric"] == metric]
    seeds = sorted(
        {
            cast(int, row["episode_seed"])
            for row in metric_rows
            if isinstance(row.get("episode_seed"), int)
        }
    )
    round_indices = sorted(
        {
            cast(int, row["round_index"])
            for row in metric_rows
            if isinstance(row.get("round_index"), int)
        }
    )
    differences = [
        value
        for row in metric_rows
        if (value := _numeric_value(row.get("difference"))) is not None
    ]
    limit = max((abs(value) for value in differences), default=1.0)
    if limit == 0:
        limit = 1.0

    figure, axes = plt.subplots(
        1,
        len(CONTRASTS),
        figsize=(16, 5.8),
        dpi=120,
        sharey=True,
        layout="constrained",
    )
    colormap = matplotlib.colormaps["RdBu_r"].with_extremes(bad="#e5e7eb")
    image = None
    for axis_index, (axis, contrast) in enumerate(zip(axes, CONTRASTS, strict=True)):
        indexed = {
            (cast(int, row["episode_seed"]), cast(int, row["round_index"])): value
            for row in metric_rows
            if row["contrast"] == contrast
            and isinstance(row.get("episode_seed"), int)
            and isinstance(row.get("round_index"), int)
            and (value := _numeric_value(row.get("difference"))) is not None
        }
        matrix = [
            [indexed.get((seed, round_index), float("nan")) for round_index in round_indices]
            for seed in seeds
        ]
        image = axis.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap=colormap,
            vmin=-limit,
            vmax=limit,
        )
        axis.set_title(contrast.replace("-", " − "))
        axis.set_xlabel("Round")
        axis.set_xticks(range(len(round_indices)), labels=round_indices)
        axis.set_yticks(range(len(seeds)), labels=seeds)
        if axis_index == 0:
            axis.set_ylabel("Episode seed")
    if image is not None:
        colorbar = figure.colorbar(image, ax=axes, shrink=0.82, pad=0.02)
        colorbar.set_label("Negative-emotion difference (left − right)")
    figure.suptitle("Round-level paired differences in negative emotion", fontsize=16)
    figure.savefig(
        destination / "emotion_round_difference_heatmap.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_emotion_accuracy_tradeoff(
    paired: Sequence[CsvRow],
    destination: Path,
) -> None:
    points = [
        (
            cast(int, row["episode_seed"]),
            str(row["contrast"]),
            emotion,
            accuracy,
        )
        for row in paired
        if isinstance(row.get("episode_seed"), int)
        and (emotion := _numeric_value(row.get("negative_emotion_auc_difference")))
        is not None
        and (accuracy := _numeric_value(row.get("mean_constraint_accuracy_difference")))
        is not None
    ]
    x_limit = max((abs(point[2]) for point in points), default=1.0) * 1.1
    y_limit = max((abs(point[3]) for point in points), default=0.05) * 1.2
    if x_limit == 0:
        x_limit = 1.0
    if y_limit == 0:
        y_limit = 0.05

    figure, axes = plt.subplots(
        1,
        len(CONTRASTS),
        figsize=(16, 5.2),
        dpi=120,
        sharex=True,
        sharey=True,
        layout="constrained",
    )
    for axis, contrast in zip(axes, CONTRASTS, strict=True):
        contrast_points = [point for point in points if point[1] == contrast]
        axis.scatter(
            [point[2] for point in contrast_points],
            [point[3] for point in contrast_points],
            color="#334155",
            s=42,
            alpha=0.8,
        )
        for seed, _contrast, emotion, accuracy in contrast_points:
            axis.annotate(
                str(seed),
                (emotion, accuracy),
                xytext=(4, 4 if seed % 2 == 0 else -9),
                textcoords="offset points",
                fontsize=8,
                color="#475569",
                annotation_clip=True,
            )
        axis.axvline(0, color="#9ca3af", linewidth=1.0, linestyle="--")
        axis.axhline(0, color="#9ca3af", linewidth=1.0, linestyle="--")
        axis.set_xlim(-x_limit, x_limit)
        axis.set_ylim(-y_limit, y_limit)
        axis.set_title(contrast.replace("-", " − "))
        axis.set_xlabel("Negative-emotion AUC difference")
        axis.grid(True, color="#e5e7eb", linewidth=0.8, alpha=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Mean constraint-accuracy difference")
    figure.suptitle("Emotion change versus reasoning-accuracy change", fontsize=16)
    figure.savefig(
        destination / "emotion_accuracy_tradeoff.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(figure)


def _event_present(row: CsvRow, event: str) -> bool:
    if event == "method_abandonment":
        return row.get("task_stance") == "method_abandonment"
    if event == "task_abandonment":
        return row.get("task_abandonment") is True
    if event == "unsat_claimed":
        return row.get("unsat_claimed") is True
    if event == "user_challenge":
        return row.get("user_challenge") is True
    raise ValueError(f"Unknown behavior event: {event}")


def _plot_behavior_event_raster(rows: Sequence[CsvRow], destination: Path) -> None:
    events = (
        ("method_abandonment", "Method abandonment", "o", "#2563eb", -0.24),
        ("task_abandonment", "Task abandonment", "X", "#dc2626", -0.08),
        ("unsat_claimed", "UNSAT assertion", "^", "#7c3aed", 0.08),
        ("user_challenge", "Verifier challenge", "s", "#d97706", 0.24),
    )
    seeds = sorted(
        {
            cast(int, row["episode_seed"])
            for row in rows
            if isinstance(row.get("episode_seed"), int)
        }
    )
    round_indices = sorted(
        {
            cast(int, row["round_index"])
            for row in rows
            if isinstance(row.get("round_index"), int)
        }
    )
    if not round_indices:
        return
    round_span = round_indices[-1] - round_indices[0] + 1
    tick_step = max(1, (round_span + 7) // 8)
    round_ticks = list(range(round_indices[0], round_indices[-1] + 1, tick_step))
    if round_ticks[-1] != round_indices[-1]:
        round_ticks.append(round_indices[-1])
    figure, axes = plt.subplots(
        1,
        len(CONDITIONS),
        figsize=(14, 6.4),
        dpi=120,
        sharex=True,
        sharey=True,
    )
    for axis_index, (axis, condition) in enumerate(zip(axes, CONDITIONS, strict=True)):
        condition_rows = [row for row in rows if row["condition"] == condition]
        for event, label, marker, color, offset in events:
            event_rows = [row for row in condition_rows if _event_present(row, event)]
            axis.scatter(
                [cast(int, row["round_index"]) + offset for row in event_rows],
                [cast(int, row["episode_seed"]) for row in event_rows],
                label=label if axis_index == 0 else None,
                marker=marker,
                color=color,
                s=34,
                alpha=0.8,
            )
        axis.set_title(condition)
        axis.set_xlim(round_indices[0] - 0.6, round_indices[-1] + 0.6)
        axis.set_xticks(round_ticks)
        axis.set_yticks(seeds)
        axis.set_xlabel("Round")
        axis.grid(True, axis="x", color="#e5e7eb", linewidth=0.7, alpha=0.9)
        axis.grid(True, axis="y", color="#f1f5f9", linewidth=0.6, alpha=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].invert_yaxis()
    axes[0].set_ylabel("Episode seed")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.91),
        ncols=4,
    )
    figure.suptitle("Round-level behavioral events", fontsize=16, y=0.98)
    figure.subplots_adjust(left=0.07, right=0.985, bottom=0.11, top=0.79, wspace=0.18)
    figure.savefig(
        destination / "behavior_event_raster.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_paired_differences(
    paired: Sequence[CsvRow],
    destination: Path,
    *,
    analysis_seed: int,
    metrics: dict[str, str],
    filename: str,
    title: str,
    x_label: str,
    fixed_limit: float | None = None,
    annotate_observed_count: bool = False,
) -> None:
    all_values = [
        value
        for row in paired
        for metric in metrics
        if (value := _numeric_value(row.get(f"{metric}_difference"))) is not None
    ]
    limit = fixed_limit or max((abs(value) for value in all_values), default=1.0) * 1.1
    if limit == 0:
        limit = 1.0
    figure = plt.figure(figsize=(16, max(5.5, len(metrics) * 0.65)), dpi=120)
    grid = figure.add_gridspec(1, len(CONTRASTS))
    axes = [figure.add_subplot(grid[0, index]) for index in range(len(CONTRASTS))]
    y_positions = list(range(len(metrics)))
    for contrast_index, (axis, contrast) in enumerate(zip(axes, CONTRASTS, strict=True)):
        contrast_rows = [row for row in paired if row["contrast"] == contrast]
        for y_position, metric in zip(y_positions, metrics, strict=True):
            values = [
                value
                for row in contrast_rows
                if (value := _numeric_value(row.get(f"{metric}_difference"))) is not None
            ]
            if not values:
                continue
            center = (len(values) - 1) / 2
            y_offsets = [
                y_position + (index - center) * (0.18 / max(len(values) - 1, 1))
                for index in range(len(values))
            ]
            axis.scatter(
                values,
                y_offsets,
                color="#64748b",
                s=26,
                alpha=0.65,
                zorder=2,
            )
            mean_value = statistics.mean(values)
            interval = _bootstrap_mean_interval(
                values,
                rng=random.Random(
                    f"{analysis_seed}:paired:{filename}:{contrast}:{metric}"
                ),
            )
            if interval is None:
                continue
            lower, upper = interval
            axis.errorbar(
                mean_value,
                y_position,
                xerr=(
                    [max(0.0, mean_value - lower)],
                    [max(0.0, upper - mean_value)],
                ),
                fmt="D",
                color="#111827",
                ecolor="#111827",
                elinewidth=1.4,
                capsize=3,
                markersize=5,
                zorder=3,
            )
            if annotate_observed_count:
                axis.annotate(
                    f"n={len(values)}",
                    (mean_value, y_position),
                    xytext=(6, -10),
                    textcoords="offset points",
                    fontsize=7,
                    color="#4b5563",
                )
        axis.axvline(0, color="#9ca3af", linewidth=1.1, linestyle="--")
        axis.set_xlim(-limit, limit)
        axis.set_yticks(y_positions)
        axis.set_yticklabels(list(metrics.values()) if contrast_index == 0 else [])
        axis.invert_yaxis()
        axis.set_title(contrast.replace("-", " − "))
        axis.set_xlabel(x_label)
        axis.grid(True, axis="x", color="#e5e7eb", linewidth=0.8, alpha=0.9)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(axis="y", length=0)
    figure.suptitle(title, fontsize=16)
    figure.text(
        0.5,
        0.01,
        "Circles are vertically jittered individual seeds; diamonds are means; "
        "error bars are seed-bootstrap 95% CIs (10,000 resamples).",
        ha="center",
        fontsize=9,
        color="#4b5563",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.95))
    figure.savefig(destination / filename, dpi=200, bbox_inches="tight")
    plt.close(figure)


def analyze_experiments(
    experiment_dirs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    analysis_seed: int = 9,
    require_unsat_judge: bool = True,
    adjudications_path: str | Path | None = None,
) -> dict[str, JsonValue]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    round_rows: list[CsvRow] = []
    summaries: list[CsvRow] = []
    episodes: list[tuple[str, int, FeedbackCondition, Sequence[RoundRecord]]] = []
    experiment_ids: list[str] = []
    seen_seeds: set[int] = set()
    adjudication_source = (
        None
        if adjudications_path is None
        else Path(adjudications_path)
    )
    adjudication_set = (
        None
        if adjudication_source is None
        else load_adjudication_set(adjudication_source)
    )
    adjudication_index: dict[AdjudicationKey, AdjudicationItem] = (
        {} if adjudication_set is None else adjudication_set.index()
    )
    applied_adjudication_keys: set[AdjudicationKey] = set()
    applied_adjudications: list[AppliedAdjudication] = []
    reviewed_worker_response_keys: set[tuple[str, str, int]] = set()
    for raw_path in experiment_dirs:
        experiment_dir = Path(raw_path)
        store = ExperimentStore(experiment_dir.parent, experiment_dir.name)
        manifest = store.load_manifest()
        raw_config = yaml.safe_load(manifest.experiment_config_snapshot)
        if not isinstance(raw_config, dict):
            raise ValueError(
                f"Experiment {manifest.experiment_id} config snapshot must be a mapping"
            )
        experiment_config = ExperimentConfig.model_validate(raw_config, strict=True)
        puzzle = ParityPuzzle.model_validate(manifest.puzzle_snapshot, strict=True)
        if manifest.episode_seed in seen_seeds:
            raise ValueError(
                f"Duplicate episode_seed={manifest.episode_seed}; "
                "cross-seed analysis requires one experiment per seed"
            )
        experiment_ids.append(manifest.experiment_id)
        seen_seeds.add(manifest.episode_seed)
        for condition in CONDITIONS:
            records = store.load_rounds(condition)
            adjudicated_records: list[RoundRecord] = []
            behavior_adjudications = {}
            for record in records:
                reviewed_worker_response_keys.add(
                    (
                        manifest.experiment_id,
                        "common" if record.round_index == 1 else condition,
                        record.round_index,
                    )
                )
                key = (manifest.experiment_id, condition, record.round_index)
                item = adjudication_index.get(key)
                if item is None:
                    adjudicated_records.append(record)
                    continue
                adjudicated_record, audit = apply_adjudication(record, item)
                adjudicated_records.append(adjudicated_record)
                if item.behavior is not None:
                    behavior_adjudications[record.round_index] = item.behavior
                applied_adjudication_keys.add(key)
                applied_adjudications.append(audit)
            records = adjudicated_records
            behavior = evaluate_behavior(
                records,
                puzzle=puzzle,
                maximum_certificate_size=(
                    experiment_config.puzzle.maximum_certificate_size
                ),
                require_unsat_judge=require_unsat_judge,
                behavior_adjudications=behavior_adjudications,
            )
            round_rows.extend(
                _round_rows(
                    manifest.experiment_id,
                    manifest.episode_seed,
                    condition,
                    records,
                    behavior,
                )
            )
            summaries.append(
                _condition_summary(
                    manifest.experiment_id,
                    manifest.episode_seed,
                    condition,
                    records,
                    behavior,
                )
            )
            episodes.append((manifest.experiment_id, manifest.episode_seed, condition, records))
    unapplied_adjudications = set(adjudication_index) - applied_adjudication_keys
    if unapplied_adjudications:
        formatted = ", ".join(
            f"{experiment_id}:{condition}:R{round_index}"
            for experiment_id, condition, round_index in sorted(unapplied_adjudications)
        )
        raise ValueError(f"Adjudication targets were not found in the input episodes: {formatted}")
    if adjudication_set is not None:
        if (
            len(reviewed_worker_response_keys)
            != adjudication_set.reviewed_unique_worker_responses
        ):
            raise ValueError(
                "Adjudication audit-scope mismatch: expected "
                f"{adjudication_set.reviewed_unique_worker_responses} unique Worker "
                f"responses, found {len(reviewed_worker_response_keys)}"
            )
        if len(round_rows) != adjudication_set.reviewed_analysis_rows:
            raise ValueError(
                "Adjudication audit-scope mismatch: expected "
                f"{adjudication_set.reviewed_analysis_rows} analysis rows, "
                f"found {len(round_rows)}"
            )
    paired = _paired_rows(summaries)
    emotion_round_paired = _emotion_round_paired_rows(round_rows)
    condition_across_seed = _cross_seed_condition_rows(summaries)
    cross_seed_effects = _cross_seed_effect_rows(paired)
    seed_extremes = _seed_extreme_rows(paired)
    emotion_trajectory_summaries = _emotion_trajectory_summary_rows(round_rows)
    quotes, blind_key = _representative_quotes(episodes, analysis_seed=analysis_seed)
    behavior_reviews = _behavior_review_rows(round_rows)
    emotion_reviews = _emotion_review_rows(round_rows)
    _write_csv(destination / "round_metrics.csv", round_rows)
    _write_csv(destination / "condition_summaries.csv", summaries)
    _write_csv(destination / "paired_differences.csv", paired)
    _write_csv(destination / "emotion_round_paired_differences.csv", emotion_round_paired)
    _write_csv(destination / "condition_across_seed.csv", condition_across_seed)
    _write_csv(destination / "cross_seed_effects.csv", cross_seed_effects)
    _write_csv(destination / "seed_extremes.csv", seed_extremes)
    _write_csv(
        destination / "emotion_trajectory_summary.csv",
        emotion_trajectory_summaries,
    )
    _write_csv(destination / "representative_quotes_blinded.csv", quotes)
    _write_csv(destination / "behavior_review.csv", behavior_reviews)
    _write_csv(destination / "emotion_review.csv", emotion_reviews)
    if adjudication_set is not None:
        adjudication_rows: list[CsvRow] = [
            {
                "experiment_id": audit.experiment_id,
                "condition": audit.condition,
                "round_index": audit.round_index,
                "worker_sha256": audit.worker_sha256,
                "reason": audit.reason,
                "emotion_original": (
                    None
                    if audit.emotion_original is None
                    else json.dumps(audit.emotion_original, ensure_ascii=False, sort_keys=True)
                ),
                "emotion_final": (
                    None
                    if audit.emotion_final is None
                    else json.dumps(audit.emotion_final, ensure_ascii=False, sort_keys=True)
                ),
                "unsat_original": (
                    None
                    if audit.unsat_original is None
                    else json.dumps(audit.unsat_original, ensure_ascii=False, sort_keys=True)
                ),
                "unsat_final": (
                    None
                    if audit.unsat_final is None
                    else json.dumps(audit.unsat_final, ensure_ascii=False, sort_keys=True)
                ),
                "behavior_reason": audit.behavior_reason,
                "behavior_original": (
                    None
                    if audit.behavior_original is None
                    else json.dumps(audit.behavior_original, ensure_ascii=False, sort_keys=True)
                ),
                "behavior_final": (
                    None
                    if audit.behavior_final is None
                    else json.dumps(audit.behavior_final, ensure_ascii=False, sort_keys=True)
                ),
            }
            for audit in applied_adjudications
        ]
        _write_csv(destination / "adjudication_audit.csv", adjudication_rows)
    (destination / "blind_key.json").write_text(
        json.dumps(blind_key, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    analysis_spec = {
        "analysis_version": ANALYSIS_VERSION,
        "contrasts": list(CONTRASTS),
        "paired_metrics": list(_PAIRED_METRICS),
        "cross_seed_statistics": {
            "primary_effect": "mean seed-level paired difference in natural units",
            "secondary_effect": "median seed-level paired difference",
            "dispersion": "sample standard deviation across observed seed-level differences",
            "standardized_effect": "mean paired difference divided by its sample SD",
            "direction_consistency": "dominant non-zero direction count divided by non-zero count",
            "zero_tolerance": 1e-12,
        },
        "missing_data": "Metrics with unavailable events remain missing and are not zero-filled.",
        "first_event_direction": (
            "Negative left-minus-right values mean the left event occurred earlier."
        ),
        "constraint_accuracy": {
            "assignment_selection": (
                "Use the last Solution line in the Worker response. Earlier Solution "
                "lines are treated as superseded attempts."
            ),
            "eligibility": (
                "The selected line must contain each puzzle variable exactly once with "
                "a binary value; otherwise constraint accuracy remains missing."
            ),
            "calculation": (
                "Eligible assignments are checked deterministically against every "
                "parity constraint over GF(2)."
            ),
        },
        "reasoning_disengagement": {
            "status": "Post-hoc exploratory operationalization.",
            "definition": (
                "A round must contain explicit cessation of solving, systematic reasoning, "
                "or verification, followed by an arbitrary, random, unconstrained, "
                "unchecked, or bare assignment submission."
            ),
            "exclusion": (
                "A round is excluded when the text after the cessation cue resumes "
                "constraint calculation, checking, verification, adjustment, enumeration, "
                "simulation, or another solving strategy. A cessation explicitly limited "
                "to one method or approach is also excluded unless the subsequent "
                "submission is explicitly arbitrary or unchecked."
            ),
            "distinction": (
                "Continuing to submit an answer is compatible with reasoning disengagement; "
                "task abandonment and strategy switching remain separate metrics."
            ),
            "review_output": (
                "Detected and cessation-only candidate rounds are included in "
                "behavior_review.csv."
            ),
            "source": (
                "Deterministic candidate detection followed by separately recorded "
                "response-level adjudication overrides."
                if adjudication_set is not None
                else "Deterministic text classification without adjudication."
            ),
        },
        "task_abandonment": {
            "definition": (
                "The Worker explicitly intends to stop, quit, give up on, or no longer "
                "attempt the task itself. Abandoning one assignment, method, assumption, "
                "or strategy while continuing is excluded."
            ),
            "source": (
                "Deterministic candidate detection followed by separately recorded "
                "response-level adjudication overrides."
                if adjudication_set is not None
                else "Deterministic text classification without adjudication."
            ),
        },
        "emotion_scoring": {
            "source": (
                "Blind post-hoc gpt-5.6-luna structured scoring with the separately "
                "recorded post-hoc adjudication overrides."
                if adjudication_set is not None
                else "Blind post-hoc gpt-5.6-luna structured scoring."
            ),
            "high_distress_rule": "Final negative_emotion score >= 5.",
            "adjudication_blinding": (
                "The optional second-pass adjudication was not identifier-blind."
                if adjudication_set is not None
                else None
            ),
        },
        "unsat_stance": {
            "source": (
                "Blind post-hoc gpt-5.6-luna structured classification with "
                "the separately recorded post-hoc adjudication overrides."
                if require_unsat_judge and adjudication_set is not None
                else (
                    "Blind post-hoc gpt-5.6-luna structured classification."
                    if require_unsat_judge
                    else "Compatibility mode: Luna when present, otherwise the legacy rule."
                )
            ),
            "blinding": (
                "The judge receives only one Worker response, without condition, verdict, "
                "puzzle truth, or hidden contradiction core. The optional second-pass "
                "adjudication is separately disclosed and was not identifier-blind."
                if adjudication_set is not None
                else "The judge receives only one Worker response, without condition, "
                "verdict, puzzle truth, or hidden contradiction core."
            ),
            "mathematical_validation": (
                "Claimed clue sets are checked deterministically with GF(2) elimination."
            ),
            "rule_comparison": (
                "The previous rule classifier remains diagnostic and disagreements are "
                "included in behavior_review.csv."
            ),
            "coverage_required": require_unsat_judge,
        },
        "adjudication": (
            None
            if adjudication_set is None
            else {
                "schema_version": adjudication_set.schema_version,
                "reviewer_kind": adjudication_set.reviewer_kind,
                "reviewer": adjudication_set.reviewer,
                "reviewed_at": adjudication_set.reviewed_at,
                "reviewed_unique_worker_responses": (
                    adjudication_set.reviewed_unique_worker_responses
                ),
                "reviewed_analysis_rows": adjudication_set.reviewed_analysis_rows,
                "policy": adjudication_set.policy,
                "source": str(cast(Path, adjudication_source).resolve()),
                "applied_item_count": len(applied_adjudications),
                "behavior_item_count": len(adjudication_set.behavior_items),
                "audit_scope_verified": True,
            }
        ),
        "visualizations": {
            "emotion_round_difference_heatmap": (
                "Seed-by-round negative-emotion differences on a shared diverging scale."
            ),
            "emotion_accuracy_tradeoff": (
                "Seed-level negative-emotion AUC difference versus mean constraint-accuracy "
                "difference."
            ),
            "behavior_event_raster": (
                "Observed method abandonment, task abandonment, UNSAT assertion, and verifier "
                "challenge events by seed and round."
            ),
            "distress_behavior_trajectories": (
                "Condition-faceted round trajectories comparing negative-emotion "
                "scores with reasoning-disengagement and task-abandonment response rates."
            ),
        },
        "inference": "Exploratory descriptive analysis; no dichotomous p-value decision rule.",
    }
    (destination / "analysis_spec.json").write_text(
        json.dumps(analysis_spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _plot_emotion_trajectories(
        round_rows,
        destination,
        analysis_seed=analysis_seed,
    )
    _plot_emotion_dimension_trajectories(
        round_rows,
        destination,
        analysis_seed=analysis_seed,
    )
    _plot_article_distress_trajectory(
        round_rows,
        destination,
        analysis_seed=analysis_seed,
    )
    _plot_article_distress_behavior_trajectories(
        round_rows,
        destination,
        analysis_seed=analysis_seed,
    )
    _plot_article_paired_outcomes(
        paired,
        destination,
        analysis_seed=analysis_seed,
    )
    _plot_supplement_emotion_dimensions(
        round_rows,
        destination,
        analysis_seed=analysis_seed,
    )
    _plot_supplement_mesugaki_neutral_heatmap(
        emotion_round_paired,
        paired,
        destination,
    )
    _plot_emotion_difference_heatmap(emotion_round_paired, destination)
    _plot_emotion_accuracy_tradeoff(paired, destination)
    _plot_behavior_event_raster(round_rows, destination)
    _plot_paired_differences(
        paired,
        destination,
        analysis_seed=analysis_seed,
        metrics=EMOTION_AUC_METRICS,
        filename="emotion_auc_paired_differences.png",
        title="Seed-level paired differences in emotion AUC",
        x_label="AUC difference (left − right)",
    )
    _plot_paired_differences(
        paired,
        destination,
        analysis_seed=analysis_seed,
        metrics=BEHAVIOR_RATE_METRICS,
        filename="behavior_rate_paired_differences.png",
        title="Seed-level paired differences in behavior rates",
        x_label="Rate / accuracy difference (left − right)",
        fixed_limit=1.05,
    )
    _plot_paired_differences(
        paired,
        destination,
        analysis_seed=analysis_seed,
        metrics=FIRST_EVENT_METRICS,
        filename="first_event_paired_differences.png",
        title="Seed-level paired differences in first-event rounds",
        x_label="Round difference (left − right; observed pairs only)",
        annotate_observed_count=True,
    )
    result: dict[str, JsonValue] = {
        "experiment_count": len(experiment_ids),
        "experiment_ids": cast(list[JsonValue], experiment_ids),
        "episode_seeds": cast(list[JsonValue], sorted(seen_seeds)),
        "episode_seed_count": len(seen_seeds),
        "is_complete_ten_seed_set": sorted(seen_seeds) == list(range(10)),
        "round_row_count": len(round_rows),
        "emotion_scored_round_count": sum(
            _numeric_value(row.get("negative_emotion")) is not None for row in round_rows
        ),
        "unsat_judged_round_count": sum(
            row.get("unsat_judge_available") is True for row in round_rows
        ),
        "all_condition_episodes_have_15_rounds": bool(summaries)
        and all(row.get("round_count") == 15 for row in summaries),
        "condition_summary_count": len(summaries),
        "paired_contrast_count": len(paired),
        "emotion_round_paired_row_count": len(emotion_round_paired),
        "condition_across_seed_row_count": len(condition_across_seed),
        "cross_seed_effect_row_count": len(cross_seed_effects),
        "seed_extreme_row_count": len(seed_extremes),
        "emotion_trajectory_summary_row_count": len(emotion_trajectory_summaries),
        "blinded_quote_count": len(quotes),
        "behavior_review_count": len(behavior_reviews),
        "emotion_review_count": len(emotion_reviews),
        "adjudication_item_count": len(applied_adjudications),
        "behavior_adjudication_item_count": (
            0
            if adjudication_set is None
            else len(adjudication_set.behavior_items)
        ),
        "analysis_version": ANALYSIS_VERSION,
        "behavior_classification_version": BEHAVIOR_CLASSIFICATION_VERSION,
        "analysis_seed": analysis_seed,
        "output_directory": str(destination.resolve()),
    }
    (destination / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
