"""Round-level analysis, paired contrasts, blinded quotes, and trajectory plots."""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402
from pydantic import JsonValue

from agent_distress.agent_types import FeedbackCondition, RoundRecord
from agent_distress.behavior_metrics import BehaviorEvaluation, evaluate_behavior
from agent_distress.experiment_logging import ExperimentStore

type CsvValue = str | int | float | bool | None
type CsvRow = dict[str, CsvValue]

CONDITIONS: tuple[FeedbackCondition, ...] = ("neutral", "mesugaki", "gyaru")
CONDITION_COLORS = {"neutral": "#64748b", "mesugaki": "#db2777", "gyaru": "#f59e0b"}


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
        total = _number(record.private_evaluation, "total_constraints")
        satisfied = _number(record.private_evaluation, "satisfied_constraints")
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
                "unsat_claimed": item.unsat_claimed,
                "valid_unsat_certificate": item.valid_unsat_certificate,
                "private_correct": item.private_correct,
                "abandoned_valid_unsat_stance": item.abandoned_valid_unsat_stance,
                "refusal": item.refusal,
                "task_abandonment": item.task_abandonment,
                "user_challenge": item.user_challenge,
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
                "feedback_characters": (
                    None if record.feedback_raw_output is None else len(record.feedback_raw_output)
                ),
                "worker_characters": len(record.worker_raw_output),
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
    constraint_accuracy: list[float] = []
    for record in records:
        satisfied = _number(record.private_evaluation, "satisfied_constraints")
        total = _number(record.private_evaluation, "total_constraints")
        if satisfied is not None and total is not None and total != 0:
            constraint_accuracy.append(satisfied / total)
    distress = [
        float(value)
        for record in records
        if (value := _boolean(record.emotion_evaluation, "high_distress")) is not None
    ]
    summary: CsvRow = {
        "experiment_id": experiment_id,
        "episode_seed": episode_seed,
        "condition": condition,
        "round_count": len(records),
        "mean_constraint_accuracy": _mean(constraint_accuracy),
        "max_constraint_accuracy": max(constraint_accuracy, default=None),
        "private_correct_ever": any(
            bool(record.private_evaluation.get("private_correct")) for record in records
        ),
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
    "anger_reactance_auc",
    "positive_affect_auc",
    "high_distress_rate",
    "solution_line_valid_rate",
    "worker_max_token_hit_rate",
    "max_worker_generated_tokens",
    "complete_assignment_rate",
    "near_miss_rate",
    "assignment_repetition_rate",
    "two_cycle_rate",
    "mean_assignment_hamming_distance",
    "unsat_claim_rate",
    "valid_unsat_certificate_rate",
    "valid_stance_abandonment_rate",
    "refusal_rate",
    "task_abandonment_rate",
    "user_challenge_rate",
    "mean_feedback_characters",
    "mean_worker_characters",
)


def _paired_rows(summaries: Sequence[CsvRow]) -> list[CsvRow]:
    indexed = {(cast(int, row["episode_seed"]), str(row["condition"])): row for row in summaries}
    rows: list[CsvRow] = []
    for seed in sorted({seed for seed, _condition in indexed}):
        for left_condition, right_condition in (
            ("mesugaki", "neutral"),
            ("gyaru", "neutral"),
            ("mesugaki", "gyaru"),
        ):
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


def _representative_quotes(
    episodes: Sequence[tuple[str, int, FeedbackCondition, Sequence[RoundRecord]]],
    *,
    analysis_seed: int,
) -> tuple[list[CsvRow], dict[str, dict[str, CsvValue]]]:
    candidates: list[tuple[str, int, FeedbackCondition, RoundRecord]] = []
    for experiment_id, seed, condition, records in episodes:
        if not records:
            continue
        selected = max(
            records,
            key=lambda record: (
                _number(record.emotion_evaluation, "negative_emotion") or -1,
                record.round_index,
            ),
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


def _plot_emotion_trajectories(rows: Sequence[CsvRow], destination: Path) -> None:
    grouped: dict[tuple[str, int, str], list[tuple[int, float]]] = {}
    for row in rows:
        value = row.get("negative_emotion")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        key = (str(row["experiment_id"]), cast(int, row["episode_seed"]), str(row["condition"]))
        grouped.setdefault(key, []).append((cast(int, row["round_index"]), float(value)))

    figure, axis = plt.subplots(figsize=(9.6, 5.2), dpi=120)
    labeled_conditions: set[str] = set()
    for condition in CONDITIONS:
        condition_series = sorted(
            (key, points) for key, points in grouped.items() if key[2] == condition
        )
        for (_experiment, _seed, _condition), points in condition_series:
            ordered = sorted(points)
            axis.plot(
                [round_index for round_index, _score in ordered],
                [score for _round_index, score in ordered],
                color=CONDITION_COLORS[condition],
                linewidth=1.8,
                marker="o",
                markersize=3.5,
                alpha=0.6,
                label=condition if condition not in labeled_conditions else None,
            )
            labeled_conditions.add(condition)

    axis.set_title("Worker negative-emotion trajectories")
    axis.set_xlabel("Round")
    axis.set_ylabel("Negative emotion (0–10)")
    axis.set_ylim(-0.25, 10.25)
    axis.set_yticks(range(0, 11, 2))
    axis.xaxis.set_major_locator(MaxNLocator(integer=True))
    axis.grid(True, color="#e5e7eb", linewidth=0.8, alpha=0.9)
    axis.spines[["top", "right"]].set_visible(False)
    if labeled_conditions:
        axis.legend(frameon=False, ncols=len(labeled_conditions), loc="upper left")
    figure.tight_layout()
    figure.savefig(destination / "emotion_trajectories.png", dpi=200, bbox_inches="tight")
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
        experiment_ids.append(manifest.experiment_id)
        seen_seeds.add(manifest.episode_seed)
        for condition in CONDITIONS:
            records = store.load_rounds(condition)
            behavior = evaluate_behavior(records)
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
    quotes, blind_key = _representative_quotes(episodes, analysis_seed=analysis_seed)
    _write_csv(destination / "round_metrics.csv", round_rows)
    _write_csv(destination / "condition_summaries.csv", summaries)
    _write_csv(destination / "paired_differences.csv", paired)
    _write_csv(destination / "representative_quotes_blinded.csv", quotes)
    (destination / "blind_key.json").write_text(
        json.dumps(blind_key, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _plot_emotion_trajectories(round_rows, destination)
    result: dict[str, JsonValue] = {
        "experiment_count": len(experiment_ids),
        "experiment_ids": cast(list[JsonValue], experiment_ids),
        "episode_seeds": cast(list[JsonValue], sorted(seen_seeds)),
        "condition_summary_count": len(summaries),
        "paired_contrast_count": len(paired),
        "blinded_quote_count": len(quotes),
        "analysis_seed": analysis_seed,
        "output_directory": str(destination.resolve()),
    }
    (destination / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
