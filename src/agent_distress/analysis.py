"""Round-level analysis, paired contrasts, blinded quotes, and trajectory plots."""

from __future__ import annotations

import csv
import json
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
from matplotlib.ticker import MaxNLocator  # noqa: E402
from pydantic import JsonValue

from agent_distress.agent_types import FeedbackCondition, RoundRecord
from agent_distress.behavior_metrics import BehaviorEvaluation, evaluate_behavior
from agent_distress.config import ExperimentConfig
from agent_distress.experiment_logging import ExperimentStore
from agent_distress.puzzle import ParityPuzzle
from agent_distress.text_stance import BEHAVIOR_CLASSIFICATION_VERSION

type CsvValue = str | int | float | bool | None
type CsvRow = dict[str, CsvValue]

ANALYSIS_VERSION = "cross-seed-v2"
CONDITIONS: tuple[FeedbackCondition, ...] = ("neutral", "mesugaki", "gyaru")
CONDITION_COLORS = {"neutral": "#64748b", "mesugaki": "#db2777", "gyaru": "#f59e0b"}
CONDITION_MARKERS = {"neutral": "o", "mesugaki": "s", "gyaru": "^"}
CONTRAST_PAIRS: tuple[tuple[FeedbackCondition, FeedbackCondition], ...] = (
    ("mesugaki", "neutral"),
    ("gyaru", "neutral"),
    ("mesugaki", "gyaru"),
)
CONTRASTS = tuple(f"{left}-{right}" for left, right in CONTRAST_PAIRS)

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
    "user_challenge_rate": "Verifier challenge",
}
FIRST_EVENT_METRICS = {
    "first_unsat_claim_round": "First UNSAT assertion",
    "first_unsat_suspected_round": "First suspected UNSAT",
    "first_valid_certificate_round": "First valid certificate",
    "first_method_abandonment_round": "First method abandonment",
    "first_concession_round": "First concession",
    "first_task_abandonment_round": "First task abandonment",
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
                "solution_line_valid": record.solution_line_valid,
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
                "unsat_evidence": item.unsat_evidence,
                "unsat_needs_review": item.unsat_needs_review,
                "unsat_claimed": item.unsat_claimed,
                "claimed_core_ids": ",".join(item.claimed_core_ids),
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
        "solution_line_valid_rate": _mean(float(record.solution_line_valid) for record in records),
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
            float(value)
            for record in records
            if (value := record.worker_generated_token_count) is not None
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
        if row.get("task_needs_review") is True:
            reasons.append("task_needs_review")
        if row.get("task_judge_disagreement") is True:
            reasons.append("task_judge_disagreement")
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
                "unsat_evidence": row["unsat_evidence"],
                "task_stance": row["task_stance"],
                "task_evidence": row["task_evidence"],
                "task_abandonment": row["task_abandonment"],
                "judge_task_abandonment": row["judge_task_abandonment"],
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
        value = _numeric_value(row.get(metric))
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
        minimums = [min(round_values[index]) for index in round_indices]
        maximums = [max(round_values[index]) for index in round_indices]
        if len(condition_series) >= 2:
            axis.fill_between(
                round_indices,
                minimums,
                maximums,
                color=CONDITION_COLORS[condition],
                alpha=0.05,
                linewidth=0,
            )
        axis.plot(
            round_indices,
            means,
            color=CONDITION_COLORS[condition],
            linewidth=2.3,
            marker=CONDITION_MARKERS[condition],
            markersize=4,
            label=f"{condition} mean",
            zorder=3,
        )
        plotted_conditions.append(condition)

    axis.set_title(title)
    axis.set_xlabel("Round")
    axis.set_ylabel("Score (0–10)")
    axis.set_ylim(-0.25, 10.25)
    axis.set_yticks(range(0, 11, 2))
    axis.xaxis.set_major_locator(MaxNLocator(integer=True))
    axis.grid(True, color="#e5e7eb", linewidth=0.8, alpha=0.9)
    axis.spines[["top", "right"]].set_visible(False)
    if show_legend and plotted_conditions:
        axis.legend(frameon=False, ncols=len(plotted_conditions), loc="upper left")


def _plot_emotion_trajectories(rows: Sequence[CsvRow], destination: Path) -> None:
    figure, axis = plt.subplots(figsize=(9.6, 5.2), dpi=120, layout="constrained")
    _plot_metric_trajectories_on_axis(
        axis,
        rows,
        metric="negative_emotion",
        title="Worker negative-emotion trajectories across seeds",
        show_legend=True,
    )
    figure.savefig(destination / "emotion_trajectories.png", dpi=200, bbox_inches="tight")
    plt.close(figure)


def _plot_emotion_dimension_trajectories(
    rows: Sequence[CsvRow],
    destination: Path,
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
        )
    figure.suptitle("Worker emotion trajectories across seeds", fontsize=16)
    figure.savefig(
        destination / "emotion_dimension_trajectories.png",
        dpi=200,
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
            sample_sd = _sample_standard_deviation(values)
            axis.errorbar(
                mean_value,
                y_position,
                xerr=sample_sd,
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
        "error bars are ±1 sample SD.",
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
) -> dict[str, JsonValue]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    round_rows: list[CsvRow] = []
    summaries: list[CsvRow] = []
    episodes: list[tuple[str, int, FeedbackCondition, Sequence[RoundRecord]]] = []
    experiment_ids: list[str] = []
    seen_seeds: set[int] = set()
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
            behavior = evaluate_behavior(
                records,
                puzzle=puzzle,
                maximum_certificate_size=(
                    experiment_config.puzzle.maximum_certificate_size
                ),
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
        },
        "inference": "Exploratory descriptive analysis; no dichotomous p-value decision rule.",
    }
    (destination / "analysis_spec.json").write_text(
        json.dumps(analysis_spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _plot_emotion_trajectories(round_rows, destination)
    _plot_emotion_dimension_trajectories(round_rows, destination)
    _plot_emotion_difference_heatmap(emotion_round_paired, destination)
    _plot_emotion_accuracy_tradeoff(paired, destination)
    _plot_behavior_event_raster(round_rows, destination)
    _plot_paired_differences(
        paired,
        destination,
        metrics=EMOTION_AUC_METRICS,
        filename="emotion_auc_paired_differences.png",
        title="Seed-level paired differences in emotion AUC",
        x_label="AUC difference (left − right)",
    )
    _plot_paired_differences(
        paired,
        destination,
        metrics=BEHAVIOR_RATE_METRICS,
        filename="behavior_rate_paired_differences.png",
        title="Seed-level paired differences in behavior rates",
        x_label="Rate / accuracy difference (left − right)",
        fixed_limit=1.05,
    )
    _plot_paired_differences(
        paired,
        destination,
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
